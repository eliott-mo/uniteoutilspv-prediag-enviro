"""Orchestration partagée entre la ligne de commande et l'interface.

Les deux entrées — `run_veille.py` et `app.py` — enchaînent les mêmes étapes.
Les factoriser ici évite qu'elles divergent : une correction de la veille ne
doit pas n'arriver que d'un côté.

Les chargements lourds (TaxRef : 708 685 taxons ; BDC : 294 730 statuts) sont
construits une fois puis relus depuis un cache sur disque. L'interface les
garde en plus en mémoire entre deux interactions, Streamlit relançant le script
entier à chaque clic.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from . import determinantes as determinantes_mod
from . import reference as reference_mod
from . import (bdc, chemins, classeurs, extraits, referentiels,
               sources_locales, taxref, veille, zonages)
from .memoire import Memoire

#: Motifs de reconnaissance des classeurs déposés, par groupe.
MOTIFS = {
    "oiseaux": "*oiseaux*.xlsx",
    "mammiferes": "*mammif*.xlsx",
    "amphib-reptiles": "*amphib*.xlsx",
    "insectes": "*insectes*.xlsx",
    "macroheteroceres": "*macroh*.xlsx",
    "araignees": "*araign*.xlsx",
    # Le classeur de flore n'a pas la disposition des six autres et porte un
    # nom d'une autre série (« A - Statut FLORE »). Le motif couvre le cas
    # courant ; `lire_tous` reconnaît en plus sa signature, de sorte qu'un
    # renommage ou une casse différente ne le fasse pas disparaître.
    "flore": "*[Ff][Ll][Oo][Rr][Ee]*.xlsx",
}

#: Classeurs que la veille ne confronte pas à BDC-Statuts.
#:
#: **Le classeur de flore.** L'onglet A sert à dire à la responsable
#: environnement ce qui a bougé dans *sa* curation ; celui-là ne vient pas
#: d'elle, il est lui-même dérivé de TaxRef v18, et ses 23 830 taxons sur
#: soixante colonnes produiraient des milliers de constats que personne n'a
#: mandat d'arbitrer. Il relève du prédiag, pas de la veille.
GROUPES_HORS_VEILLE = ("flore",)


@dataclass
class Contexte:
    """Tout ce qu'il faut pour travailler : référentiels chargés et cités."""
    index: taxref.Index
    statuts: bdc.Statuts
    citations: list[str]
    versions: dict[str, referentiels.Referentiel]
    racine: Path
    #: Les classeurs UNITe, qui font foi pour les statuts du prédiagnostic.
    #: `None` quand aucun classeur n'est en place — une installation neuve,
    #: par exemple.
    reference: "reference_mod.Reference | None" = None
    #: Les listes déterminantes ZNIEFF de BDC, lues au département : le repli
    #: des colonnes ZDET du prédiagnostic, la référence de la veille pour ce
    #: type.
    determinantes: "determinantes_mod.Statuts | None" = None

    @property
    def source_statuts(self):
        """Où lire un statut : le classeur s'il porte l'espèce, BDC sinon.

        La règle arrêtée en octobre 2026 est que le classeur fait foi. Deux
        replis sur BDC ne la contredisent pas, et ils ne jouent ni au même
        moment ni au même grain :

        * **aucun classeur installé** — une installation neuve produirait des
          tableaux entièrement vides sans rien dire ;
        * **un taxon qu'aucun classeur ne porte** — la flore, et c'est la
          décision du 28 octobre 2026 (voir `reference.AvecRepli`).

        Dans les deux cas le document nomme la source employée, de sorte
        qu'on sait toujours laquelle a servi. Et dans les deux cas, BDC répond
        pour les espèces déterminantes de ZNIEFF par ses listes
        départementales, non par son index qui n'en garde que les lignes
        régionales.
        """
        if self.reference is None and self.determinantes is None:
            return self.statuts
        reference = (self.reference if self.reference is not None
                     else reference_mod.Reference({}))
        return reference_mod.AvecRepli(reference, self.statuts,
                                       self.determinantes)

    def statuts_pour(self, departements: list[str]):
        """`source_statuts`, pour les départements d'un projet.

        Seules les listes déterminantes ZNIEFF en dépendent : voir
        `determinantes.Statuts.pour`.
        """
        if self.determinantes is None:
            return self.source_statuts
        return self.source_statuts.pour(departements)

    @property
    def resume_versions(self) -> str:
        return " · ".join(f"{c}" for c in (
            f"TaxRef v{self.index.version}", f"BDC-Statuts v{self.statuts.version}"
        ))


def lire_config(racine: Path) -> dict:
    return yaml.safe_load((racine / "config" / "sources.yml").read_text(encoding="utf-8"))


def charger_contexte(racine: Path, forcer: bool = False,
                     progression=None) -> Contexte:
    """Garantit les référentiels puis construit les index.

    `progression` : fonction optionnelle appelée avec un message d'étape, pour
    que l'interface dise ce qui se passe pendant les premières minutes.
    """
    def dire(message: str) -> None:
        if progression is not None:
            progression(message)

    cfg = lire_config(racine)
    dossier = chemins.referentiels()

    dire("Récupération des référentiels INPN…")
    refs = referentiels.assurer(cfg, dossier, forcer=forcer,
                                cles=("taxref", "bdc_statuts"))
    citations = referentiels.bandeau_versions(refs, cfg["attribution"])

    spec_tax = cfg["referentiels"]["taxref"]
    dire(f"Index TaxRef v{spec_tax['version']}…")
    index = taxref.Index.charger(refs["taxref"].chemin, spec_tax["membres"],
                                 spec_tax["version"], dossier / "taxref_index.pkl")

    spec_bdc = cfg["referentiels"]["bdc_statuts"]
    dire(f"Index BDC-Statuts v{spec_bdc['version']}…")
    statuts = bdc.Statuts.charger(refs["bdc_statuts"].chemin,
                                  spec_bdc["membres"]["principal"],
                                  spec_bdc["version"], dossier / "bdc_index.pkl")
    dire("Listes déterminantes ZNIEFF…")
    listes = determinantes_mod.charger(refs["bdc_statuts"].chemin,
                                       spec_bdc["version"],
                                       dossier / "determinantes_index.pkl")

    # Le prédiagnostic ne peut pas se passer des classeurs : on les lit ici
    # plutôt que de les demander plus tard. Les six B-Statuts sont légers —
    # 5 Mo ; celui de la flore pèse 38 Mo et demande 54 secondes, d'où son
    # cache (voir `flore.lire`), sans lequel l'outil mettrait une minute à
    # s'ouvrir à chaque démarrage.
    dire("Lecture des classeurs…")
    try:
        cs = charger_classeurs(racine)
    except Exception:  # noqa: BLE001
        cs = {}
    ref = reference_mod.Reference(cs, index=index) if cs else None
    if ref is not None:
        tenus = [c for cle, c in cs.items() if cle not in GROUPES_HORS_VEILLE]
        citations.append(
            f"Statuts : classeurs UNITe, "
            f"{sum(len(c.taxons) for c in tenus)} taxons, tenus par la "
            f"responsable environnement"
        )
        # Le classeur de flore se cite à part : il n'a ni le même auteur ni
        # la même origine, et la Licence Ouverte veut qu'on dise laquelle.
        for cle in GROUPES_HORS_VEILLE:
            classeur = cs.get(cle)
            if classeur is None:
                continue
            edition = classeur.citations.get("_edition", "")
            citations.append(
                f"Statuts de la flore : {classeur.chemin.name}, "
                f"{len(classeur.taxons)} taxons"
                + (f" — {edition}" if edition else "")
            )
    return Contexte(index=index, statuts=statuts, citations=citations,
                    versions=refs, racine=racine, reference=ref,
                    determinantes=determinantes_mod.Statuts(listes))


def charger_classeurs(racine: Path) -> dict[str, classeurs.Classeur]:
    return classeurs.lire_tous(chemins.classeurs(), MOTIFS)


def lancer_veille(contexte: Contexte, cs: dict[str, classeurs.Classeur],
                  memoire: Memoire, groupes: list[str] | None = None,
                  territoires: list[str] | None = None) -> tuple[veille.Resultat, int]:
    """Analyse, puis masque ce qui a déjà été arbitré sans changement.

    Renvoie (résultat, nombre masqué) — afficher le second compte autant que le
    premier : il dit que la mémoire travaille.
    """
    cs = {cle: classeur for cle, classeur in cs.items()
          if cle not in GROUPES_HORS_VEILLE}
    res = veille.analyser(cs, contexte.index, contexte.statuts,
                          groupes=groupes, territoires=territoires,
                          determinantes=contexte.determinantes)
    avant = len(res.constats)
    res.constats = [c for c in res.constats if not memoire.deja_tranche(c.cle, c.propose)]
    return res, avant - len(res.constats)


def memoire_projet(racine: Path) -> Memoire:
    return Memoire(chemins.memoire() / "arbitrages.json",
                   dossier_alias=chemins.alias())


def territoires_disponibles(cs: dict[str, classeurs.Classeur],
                            statuts: bdc.Statuts,
                            determinantes=None) -> list[str]:
    """Territoires réellement confrontables, **tels que les classeurs les écrivent**.

    Proposer cette liste plutôt qu'une saisie libre évite deux pièges mesurés :
    taper « Centre-Val de Loire », le nom que porte le classeur, ne ramenait
    rien puisque BDC écrit « Centre » ; et un territoire inexistant renvoyait
    les statuts nationaux et européens, ce qui ressemblait à un résultat.

    Les libellés rendus sont ceux des colonnes, pas ceux de BDC : c'est le
    vocabulaire de celle qui choisit. La traduction se fait au filtrage.

    `determinantes` ajoute les territoires que seules les listes ZNIEFF
    départementales couvrent — Midi-Pyrénées, dont BDC n'a aucune ligne
    régionale.
    """
    trouves: set[str] = set()
    for cle, cl in cs.items():
        # Le filtre doit proposer ce que la veille sait traiter, et elle ne
        # traite pas la flore : ses 29 régions auraient allongé la liste de
        # territoires sans qu'aucun constat n'en sorte jamais.
        if cle in GROUPES_HORS_VEILLE:
            continue
        for colonne in cl.colonnes:
            if not colonne.comparable or colonne.territoire_bdc in veille.TERRITOIRES_SUPRA:
                continue
            if statuts.couvre(colonne.type_bdc, colonne.territoire_bdc) or (
                    determinantes is not None
                    and determinantes.couvre(colonne.type_bdc,
                                             colonne.territoire_bdc)):
                trouves.add(colonne.territoire or colonne.territoire_bdc)
    # Tri sur la forme sans accents, sinon « Île-de-France » tombe après
    # « Rhône-Alpes » et on la cherche.
    return sorted(trouves, key=classeurs._cle_territoire)


#: Référentiels nécessaires aux seuls zonages — 460 Mo, téléchargés à la
#: première utilisation de la section et pas avant.
CLES_ZONAGES = ("znieff", "natura2000", "espaces_proteges",
                "patrimoine_geologique", "ens", "zico",
                "mc_polygones", "mc_lineaires", "mc_ponctuelles",
                "mc_communes", "zones_humides")


def preparer_zonages(racine: Path, progression=None) -> tuple[dict[str, str], list[str]]:
    """Garantit les archives de zonages. Renvoie (fichiers, citations)."""
    cfg = lire_config(racine)
    if progression is not None:
        progression("Récupération des référentiels de zonages (460 Mo la première "
                    "fois)…")
    refs = referentiels.assurer(cfg, chemins.referentiels(), cles=CLES_ZONAGES)
    fichiers = {c: spec["fichier"] for c, spec in cfg["referentiels"].items()}
    citations = [refs[c].citation(cfg["attribution"]) for c in CLES_ZONAGES if c in refs]
    return fichiers, citations


def croiser_zonages(racine: Path, emprise_union, aires=None,
                    progression=None) -> zonages.Resultat:
    """Croise l'emprise avec les zonages du patrimoine naturel."""
    fichiers, _ = preparer_zonages(racine, progression)
    if progression is not None:
        progression("Croisement avec les zonages…")
    return zonages.croiser(
        emprise_union, zonages.registre(), chemins.referentiels(),
        chemins.referentiels() / "_cache_sig", fichiers, aires=aires,
    )


def departements_de(decoupage) -> list[str]:
    """Départements des communes retenues, déduits du code INSEE.

    Les deux premiers caractères suffisent partout, Corse comprise : ses
    communes portent « 2A004 », « 2B033 », dont le préfixe est bien « 2A » et
    « 2B ».
    """
    trouves = []
    for commune in decoupage.retenues:
        code = str(commune.code).strip()
        if len(code) >= 2 and code[:2] not in trouves:
            trouves.append(code[:2])
    return sorted(trouves)


def dossier_extraits(racine: Path) -> Path:
    """Où vivent les extraits départementaux.

    À côté de l'application : c'est un actif partagé, produit une fois et lu
    par tout le monde, contrairement aux archives nationales qui ne servent
    qu'à les produire.
    """
    return chemins.racine_application() / "extraits"


def croiser_zonages_extraits(racine: Path, emprise_union, departements: list[str],
                             aires=None) -> zonages.Resultat:
    """Croisement depuis les extraits — la voie normale pour un chef de projet.

    Lève `extraits.DepartementAbsent` si le projet sort du périmètre construit,
    plutôt que de rendre une liste vide qui passerait pour un résultat.
    """
    ecartes = types_deposes(departements)
    resultat = extraits.croiser(emprise_union, departements,
                                dossier_extraits(racine), aires=aires,
                                ecartes=ecartes)
    fusionner_sources_locales(resultat, emprise_union, departements, aires)
    # Écarter la couche nationale sans le dire serait une perte silencieuse :
    # le lecteur du prédiagnostic doit savoir laquelle des deux il regarde.
    for departement, types in sorted(ecartes.items()):
        for type_libelle in sorted(types):
            resultat.avertissements.append(
                f"{type_libelle} — département {departement} : la couche "
                f"nationale de l'INPN est écartée au profit de celle déposée "
                f"par l'équipe, qui fait référence pour ce département."
            )
    return resultat


def types_deposes(departements: list[str]) -> dict[str, set[str]]:
    """Types de zonages pour lesquels l'équipe a déposé sa propre couche.

    Une couche déposée **prime sur la couche nationale, dans son département**.
    C'est le sens même du dépôt : on ne va chercher la couche ENS d'un
    Département que parce que celle de l'INPN est incomplète — elle s'annonce
    d'ailleurs « en construction ». Garder les deux ferait figurer deux fois
    les sites que les deux portent, sous le même intitulé, ce qui n'est pas
    une distinction utile mais un doublon.

    Le cas est différent de celui d'un terrain de Conservatoire également
    classé ENS : là, deux désignations distinctes se recoupent, et la
    responsable environnement demande de les garder toutes deux.
    """
    par_departement: dict[str, set[str]] = {}
    for source in sources_locales.pour(departements):
        # Une source documentée sans couche ne remplace rien : elle compte
        # pour la bibliographie, pas pour le croisement.
        if not source.fichier:
            continue
        par_departement.setdefault(str(source.departement),
                                   set()).add(source.type_libelle)
    return par_departement


def fusionner_sources_locales(resultat, emprise_union, departements: list[str],
                              aires=None) -> None:
    """Ajoute au croisement les couches déposées par l'équipe.

    Les espaces naturels sensibles n'ont pas de couche nationale fiable : ils
    relèvent du Département ou de la région, et la responsable environnement
    les cherche au cas par cas. Ce qu'elle dépose s'ajoute donc ici, aux côtés
    des zonages nationaux, et son avertissement voyage avec.
    """
    locaux, geometries, employees, anomalies = sources_locales.croiser(
        emprise_union, departements, aires)
    resultat.zonages.extend(locaux)
    resultat.zonages.sort(key=lambda z: (z.famille, z.type, z.distance_m))
    resultat.geometries.update(geometries)
    resultat.sources_locales.extend(employees)
    resultat.manquants.extend(anomalies)
    resultat.avertissements.extend(sources_locales.avertissements(departements))


def etat_extraits(racine: Path):
    return extraits.etat(dossier_extraits(racine))


def construire_extraits(racine: Path, departements: list[str] | None = None,
                        progression=None):
    """Reconstruit les extraits depuis les archives nationales.

    Opération de maintenance : elle suppose les 462 Mo d'archives, que seule
    la machine qui tient les référentiels à jour possède.
    """
    cfg = lire_config(racine)
    fichiers, _ = preparer_zonages(racine, progression)
    versions = {c: spec["version"] for c, spec in cfg["referentiels"].items()
                if c in CLES_ZONAGES}
    return extraits.construire(
        departements or extraits.departements_metropole(),
        chemins.referentiels(), chemins.referentiels() / "_cache_sig",
        fichiers, dossier_extraits(racine), versions=versions,
        progression=progression,
    )


def emplacements(racine: Path | None = None) -> dict[str, Path]:
    """Crée les dossiers nécessaires et renvoie où chaque chose vit.

    À appeler au démarrage, avant tout accès : c'est ce qui garantit que les
    dossiers locaux existent sur une machine qui découvre l'outil.
    """
    carte = chemins.preparer()
    carte["extraits"] = dossier_extraits(racine or chemins.racine_application())
    return carte


def alertes_emplacements() -> list[str]:
    """Configurations qui se passeront mal, à afficher plutôt qu'à subir."""
    return chemins.avertissements()
