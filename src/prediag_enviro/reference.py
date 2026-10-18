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

    def __init__(self, classeurs: dict[str, Classeur]):
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

    def __len__(self) -> int:
        return len(self._par_cd)

    def groupe_classeur(self, cd_ref: str) -> str:
        """Nom du classeur qui porte ce taxon — « macroheteroceres »…

        C'est la classification de la responsable environnement, et elle
        tranche là où TaxRef ne distingue pas : un rhopalocère et un
        hétérocère sont tous deux « Lépidoptères » dans `GROUP3_INPN`, et
        l'ordre taxonomique ne dit que « Lepidoptera ». Ses deux classeurs,
        eux, les séparent — c'est la règle posée en octobre 2026, le classeur
        fait foi.
        """
        fiche = self._par_cd.get(str(cd_ref).strip())
        return fiche.classeur.groupe if fiche is not None else ""

    def connait(self, cd_ref: str) -> bool:
        """Le taxon figure-t-il dans un classeur ?

        À distinguer d'une case vide : une espèce absente du classeur n'a
        aucun statut faute de ligne, une espèce présente peut avoir une case
        vide parce que le statut n'existe pas. Le premier cas se signale, le
        second non.
        """
        return str(cd_ref).strip() in self._par_cd

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
        fiche = self._par_cd.get(str(cd_ref).strip())
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
            trouvees.append(bdc.Entree(code=valeur, rendu=valeur,
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
