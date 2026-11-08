"""Les classeurs UNITe comme référence des statuts, pour le prédiagnostic.

**Décision d'octobre 2026.** Les statuts écrits dans un prédiagnostic viennent
désormais des classeurs que la responsable environnement tient à jour, et non
de BDC-Statuts. Elle garde ainsi le contrôle de ce qui est publié, et le fait
évoluer quand une liste change.

BDC ne disparaît pas pour autant : la veille de l'onglet A continue de
confronter les classeurs à la base nationale et de dire ce qui a bougé. Le
partage est net — **BDC surveille, le classeur fait foi**.

Pourquoi c'était le bon choix, en chiffres. Trois reproches de sa relecture
tenaient à des trous de BDC qu'aucun correctif de notre côté ne pouvait
combler : pas de statut européen pour le Hérisson, le Phoque veau-marin ni le
méconème fragile ; aucune liste rouge France pour les orthoptères, dont la
référence est un classement par domaine biogéographique étranger au modèle de
la base ; et aucune liste rouge régionale d'oiseaux en Normandie, là où il y
en a 694 en Provence. Ses classeurs, eux, portent ces valeurs.

Le coût a été mesuré avant de basculer, sur les 236 espèces d'un
prédiagnostic réel. Quatre n'y figuraient pas, dont trois déterminations
arrêtées au-dessus de l'espèce — deux familles et un genre, qu'aucun classeur
ne porterait. Une seule espèce perdait un statut.

**La limite à connaître.** Aucun des six classeurs ne couvre la flore ni les
poissons. Les relevés déposés jusqu'ici n'en contiennent pas, mais le jour où
l'un en contiendra, les colonnes resteront vides jusqu'à ce qu'elle ajoute le
classeur correspondant. C'est le revers assumé du contrôle : `connait()` dit
ce qui manque, pour qu'on le lui signale au lieu de le taire.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import bdc
from .classeurs import Classeur, ColonneStatut, LigneTaxon

#: Période telle que l'écrit un en-tête de classeur, vers celle de BDC. Les
#: deux vocabulaires existaient déjà, sans table pour les relier : la veille
#: écarte simplement les colonnes périodisées au lieu de les confronter.
_PERIODES = {
    "nicheurs": bdc.PERIODE_NICHEUR,
    "hivernants": bdc.PERIODE_HIVERNANT,
    "de passage": bdc.PERIODE_PASSAGE,
}


def _periode_bdc(colonne: ColonneStatut) -> str:
    return _PERIODES.get(colonne.periode.strip().lower(), "")


#: L'annexe que nomme l'en-tête d'une colonne de directive.
_ANNEXE = re.compile(r"(?i)annexe\s+(I{1,3}|IV|V)\b")


def _valeur_directive(colonne: ColonneStatut, valeur: str) -> str:
    """Ce qui s'imprime pour une directive : l'annexe, non le code espèce.

    **Les classeurs codent l'espèce, pas l'annexe.** La colonne « Annexe I
    directive Oiseaux » porte « A707 » pour l'Aigle de Bonelli, et « Annexe
    II directive Habitats » porte « 1304 » pour le Grand rhinolophe. Le
    tableau du prédiagnostic, lui, attend « Annexe II » — il filtrait donc
    sur un libellé que le classeur n'écrit jamais, et les deux colonnes de
    directive sortaient vides sur tout le document.

    Le code espèce n'apprend rien au lecteur ; ce qu'il veut savoir est que
    l'espèce est inscrite. L'en-tête de la colonne dit à quelle annexe, et
    la présence d'une valeur dit que oui.
    """
    trouve = _ANNEXE.search(colonne.libelle or "")
    if trouve:
        return f"Annexe {trouve.group(1).upper()}"
    return valeur


def _national(type_statut: str) -> bool:
    """Ce type de statut a-t-il une portée nationale fixe ?

    Pour ceux-là — liste rouge Europe, liste rouge France, protection
    nationale, directives, PNA — un classeur ne porte qu'une colonne, et son
    intitulé de territoire est libre : elle écrit « Protection nationale »,
    « France », ou rien du tout, là où BDC dit « France métropolitaine ».
    Exiger l'égalité des libellés ne rendait donc aucune protection nationale
    ni aucune liste rouge française. Le type suffit à désigner la colonne.

    Les types régionaux — LRR, PR, PD, ZDET — gardent la comparaison sur le
    territoire : elle y porte une colonne par région, et il faut la bonne.
    """
    return bool(bdc.TERRITOIRES_FIXES.get(type_statut))


def _correspond(colonne: ColonneStatut, type_statut: str,
                territoire: str) -> bool:
    if colonne.type_bdc != type_statut:
        return False
    if _national(type_statut):
        return True
    return colonne.territoire_bdc == territoire


@dataclass
class _Fiche:
    """Un taxon et le classeur qui le porte."""
    classeur: Classeur
    taxon: LigneTaxon


class Reference:
    """Les statuts tels que les classeurs UNITe les écrivent.

    Présente l'interface de `bdc.Statuts` — `couvre`, `entrees`, `rendu` — de
    sorte que `statuts_especes` n'a pas à savoir d'où vient la valeur.
    """

    def __init__(self, classeurs: dict[str, Classeur], index=None):
        self.classeurs = classeurs
        #: cd_nom -> fiche. Un même taxon peut figurer dans deux classeurs —
        #: la responsable environnement a reconnu des doublons entre insectes
        #: et macrohétérocères. Le premier lu l'emporte, et la veille lui
        #: signale le doublon par ailleurs.
        self._par_cd: dict[str, _Fiche] = {}
        for classeur in classeurs.values():
            for taxon in classeur.taxons:
                cd = str(taxon.cd_nom).strip()
                if cd and cd not in self._par_cd:
                    self._par_cd[cd] = _Fiche(classeur, taxon)
        #: L'index TaxRef, qui mène d'une sous-espèce à son espèce : voir
        #: `lu_comme`. Sans lui, un taxon se lit à son seul cd_ref.
        self.index = index

    def __len__(self) -> int:
        return len(self._par_cd)

    def lu_comme(self, cd_ref: str) -> str:
        """Le taxon dont la ligne répond pour ce cd_ref : lui, ou son espèce.

        **Décision du 8 novembre 2026.** Les classeurs portent l'espèce ; les
        relevés nomment parfois la sous-espèce. À Bédarieux, neuf taxons
        relevés ainsi perdaient la ligne de leur espèce, et prenaient ce que
        BDC dit de la sous-espèce — souvent rien : l'Effraie des clochers,
        relevée en *Tyto alba delicatula*, sortait sans protection, et les
        neuf sans liste rouge. Un taxon infraspécifique qu'aucun classeur ne
        porte se lit donc comme son espèce, quand un classeur la porte. Celui
        qu'un classeur porte garde sa propre ligne.
        """
        cd = str(cd_ref).strip()
        if cd in self._par_cd or self.index is None:
            return cd
        espece = self.index.espece(cd)
        return espece if espece and espece in self._par_cd else cd

    def _fiche(self, cd_ref: str) -> _Fiche | None:
        return self._par_cd.get(self.lu_comme(cd_ref))

    def groupe_classeur(self, cd_ref: str) -> str:
        """Nom du classeur qui porte ce taxon — « macroheteroceres »…

        C'est la classification de la responsable environnement, et elle
        tranche là où TaxRef ne distingue pas : un rhopalocère et un
        hétérocère sont tous deux « Lépidoptères » dans `GROUP3_INPN`, et
        l'ordre taxonomique ne dit que « Lepidoptera ». Ses deux classeurs,
        eux, les séparent — c'est la règle posée en octobre 2026, le classeur
        fait foi.
        """
        fiche = self._fiche(cd_ref)
        return fiche.classeur.groupe if fiche is not None else ""

    def connait(self, cd_ref: str) -> bool:
        """Le taxon figure-t-il dans un classeur ?

        À distinguer d'une case vide : une espèce absente du classeur n'a
        aucun statut faute de ligne, une espèce présente peut avoir une case
        vide parce que le statut n'existe pas. Le premier cas se signale, le
        second non.
        """
        return self._fiche(cd_ref) is not None

    def interroge(self, cd_ref: str, type_statut: str,
                  territoire: str) -> bool:
        """Le classeur qui porte ce taxon pose-t-il seulement la question ?

        Il fallait distinguer une troisième fois. `connait()` sépare
        « absente du classeur » de « case vide » ; restait « le classeur n'a
        pas la colonne ». Le classeur de flore n'en a aucune pour les espèces
        déterminantes de ZNIEFF : son silence là-dessus n'est pas un constat,
        c'est une question qu'il ne pose pas, et BDC-Statuts peut y répondre
        sans contredire personne.

        La nuance se joue au classeur qui porte le taxon, non à l'ensemble :
        le classeur des macrohétérocères déclare ses espèces déterminantes,
        celui de la flore non, et c'est bien celui qui porte la plante qui
        décide pour elle.
        """
        fiche = self._fiche(cd_ref)
        if fiche is None:
            return False
        return any(_correspond(colonne, type_statut, territoire)
                   for colonne in fiche.classeur.colonnes)

    # ------------------------------------------------- interface bdc.Statuts

    def couvre(self, type_statut: str, territoire: str) -> bool:
        """Un classeur porte-t-il une colonne pour ce type et ce territoire ?"""
        for classeur in self.classeurs.values():
            for colonne in classeur.colonnes:
                if _correspond(colonne, type_statut, territoire):
                    return True
        return False

    def entrees(self, cd_ref: str, type_statut: str,
                territoire: str) -> list[bdc.Entree]:
        """Les valeurs écrites pour ce taxon, ce type et ce territoire.

        Une case vide ne donne pas d'entrée : c'est bien l'absence de statut,
        et non un statut vide, qu'il faut rendre.
        """
        fiche = self._fiche(cd_ref)
        if fiche is None:
            return []
        trouvees: list[bdc.Entree] = []
        for colonne in fiche.classeur.colonnes:
            if not _correspond(colonne, type_statut, territoire):
                continue
            valeur = str(fiche.taxon.valeurs.get(colonne.index, "") or "").strip()
            if not valeur:
                continue
            # Le classeur écrit ce qui se publie : « LC », « Art. 3 »,
            # « Annexe II ». Code brut et rendu se confondent donc, là où BDC
            # distingue « NO3 » de « Art. 3 ».
            rendu = (_valeur_directive(colonne, valeur)
                     if type_statut in ("DO", "DH") else valeur)
            trouvees.append(bdc.Entree(code=valeur, rendu=rendu,
                                       periode=_periode_bdc(colonne)))
        return trouvees

    def rendu(self, cd_ref: str, type_statut: str, territoire: str,
              periode: str | None = None,
              filtre: tuple[str, ...] | None = None) -> str:
        """Ce qui s'écrit dans la cellule, ou une chaîne vide."""
        entrees = self.entrees(cd_ref, type_statut, territoire)
        if periode:
            entrees = [e for e in entrees if e.periode == periode]
        if filtre:
            entrees = [e for e in entrees if e.rendu in filtre]
        if not entrees:
            return ""
        # Plusieurs colonnes peuvent répondre — une directive citée deux fois,
        # par exemple. On joint dans l'ordre de lecture du document.
        vus: list[str] = []
        for e in entrees:
            if e.rendu not in vus:
                vus.append(e.rendu)
        return ", ".join(vus)


class AvecRepli:
    """Les classeurs, et BDC-Statuts pour les espèces qu'ils ne portent pas.

    **Décision du 28 octobre 2026.** « Le classeur fait foi » laissait la flore
    sans aucun statut : 802 plantes à Bédarieux, toutes colonnes vides, alors
    que BDC en documente près de 750 et signale six espèces protégées. Une
    colonne vide se lit « non protégée » — le document affirmait donc le
    contraire de la réalité sur un point réglementaire.

    Le repli se décide **colonne par colonne, jamais cellule par cellule.**
    Si le classeur qui porte le taxon pose la question — s'il a la colonne,
    et qu'elle est renseignée quelque part —, il fait foi jusque dans ses
    blancs : une case vide y est une absence de statut constatée, pas une
    lacune à combler. BDC ne parle que là où le classeur ne demande rien :
    taxon absent de tous les classeurs, ou type de statut dont celui qui le
    porte n'a pas de colonne.

    La nuance est venue du classeur de flore, qui n'a aucune colonne
    « déterminante ZNIEFF ». Une règle purement espèce par espèce l'aurait
    rendu muet sur ce point dès son intégration, alors que BDC y répond —
    on aurait perdu une colonne en croyant en gagner cinq.

    Le document nomme la source employée sous chaque tableau concerné —
    voir `rapport_prediag._absence_de_reference` et `_colonnes_repliees`.

    Ce que l'arrivée du classeur de flore a changé, mesuré sur Bédarieux :
    749 listes rouges France, 213 européennes et 8 protections passent de BDC
    au classeur, tandis que les 64 espèces déterminantes de ZNIEFF restent à
    BDC. Le repli n'a donc pas disparu avec le classeur — il s'est déplacé
    vers les seules colonnes que ce classeur ne porte pas.

    **Pour les espèces déterminantes de ZNIEFF, BDC répond par ses listes
    (1er novembre 2026).** 85 % de leurs lignes sont saisies au département,
    que son index range sous « Hérault » plutôt que sous « Occitanie » : le
    repli ne trouvait donc rien là où un classeur n'a pas la colonne de la
    région — 0 statut sur les 224 oiseaux, amphibiens et reptiles de
    Bédarieux, 69 avec les listes. `determinantes.Statuts` les rapporte à
    leur territoire, les écrit dans la convention des classeurs, et ne
    retient pour un projet que celles qui couvrent ses départements (`pour`).
    """

    def __init__(self, reference: Reference, statuts: bdc.Statuts,
                 determinantes=None):
        self.reference = reference
        self.statuts = statuts
        #: Les listes déterminantes ZNIEFF (`determinantes.Statuts`). Sans
        #: elles, ZDET retombe sur l'index de BDC et ses lignes régionales.
        self.determinantes = determinantes

    def __len__(self) -> int:
        return len(self.reference)

    def pour(self, departements) -> "AvecRepli":
        """Le même repli, pour les départements d'un projet.

        Seules les listes déterminantes en dépendent — voir
        `determinantes.Statuts.pour` : une colonne de classeur, une liste
        rouge ou une protection régionale valent pour toute leur région.
        """
        if self.determinantes is None:
            return self
        return AvecRepli(self.reference, self.statuts,
                         self.determinantes.pour(departements))

    def _repli(self, type_statut: str):
        """Ce que BDC dit d'un type, là où le classeur ne demande rien."""
        if type_statut == "ZDET" and self.determinantes is not None:
            return self.determinantes
        return self.statuts

    def _source(self, cd_ref: str, type_statut: str, territoire: str):
        return (self.reference
                if self.reference.interroge(cd_ref, type_statut, territoire)
                else self._repli(type_statut))

    # ------------------------------------------- ce que `Reference` ajoute

    def connait(self, cd_ref: str) -> bool:
        """Toujours la question des classeurs : BDC n'y répond pas pour eux."""
        return self.reference.connait(cd_ref)

    def groupe_classeur(self, cd_ref: str) -> str:
        return self.reference.groupe_classeur(cd_ref)

    # ------------------------------------------------- interface bdc.Statuts

    def couvre(self, type_statut: str, territoire: str) -> bool:
        """L'un ou l'autre porte-t-il ce couple type/territoire ?

        L'union est sans danger pour le choix du découpage régional, qui gate
        sur `couvre` puis départage au nombre d'espèces réellement renseignées
        (`territoire_regional`) : une région que seul BDC couvre passe la
        grille mais marque zéro sur un tableau d'espèces qu'elle connaît, et
        n'est donc retenue que là où le repli sert vraiment.
        """
        return (self.reference.couvre(type_statut, territoire)
                or self._repli(type_statut).couvre(type_statut, territoire))

    def _candidats(self, cd_ref: str) -> list[str]:
        """À qui demander, quand BDC répond pour un taxon lu comme son espèce.

        Au taxon d'abord : une liste peut nommer la sous-espèce. À l'espèce
        ensuite, que les classeurs portent et dont BDC parle le plus souvent.
        """
        lu = self.reference.lu_comme(cd_ref)
        return [cd_ref] if lu == cd_ref else [cd_ref, lu]

    def entrees(self, cd_ref: str, type_statut: str,
                territoire: str) -> list[bdc.Entree]:
        source = self._source(cd_ref, type_statut, territoire)
        if source is self.reference:
            return source.entrees(cd_ref, type_statut, territoire)
        for cd in self._candidats(cd_ref):
            trouvees = source.entrees(cd, type_statut, territoire)
            if trouvees:
                return trouvees
        return []

    def rendu(self, cd_ref: str, type_statut: str, territoire: str,
              periode: str | None = None,
              filtre: tuple[str, ...] | None = None) -> str:
        source = self._source(cd_ref, type_statut, territoire)
        if source is self.reference:
            return source.rendu(cd_ref, type_statut, territoire, periode,
                                filtre)
        for cd in self._candidats(cd_ref):
            rendu = source.rendu(cd, type_statut, territoire, periode, filtre)
            if rendu:
                return rendu
        return ""
