"""Le classeur de flore, qui ne ressemble à aucun des six B-Statuts.

Les six classeurs de la responsable environnement portent un onglet `Statuts`
et un onglet « Saisie étude » qui sert de dictionnaire de colonnes. Celui de la
flore n'a ni l'un ni l'autre : c'est **une table TaxRef v18 de 108 368 lignes
sur 117 colonnes**, une ligne par nom — synonymes compris — et une colonne par
statut. Lui appliquer le lecteur des B-Statuts ne donnait rien du tout.

Trois feuilles le rendent lisible sans rien deviner, et c'est pour ça qu'il
mérite son propre module plutôt qu'une série d'exceptions dans `classeurs` :

* **`Régions`** est son dictionnaire de colonnes — une ligne par région, avec
  l'indice de sa colonne de protection, de liste rouge, d'espèces exotiques
  envahissantes et de messicoles. Il signale même les régions fusionnées.
  Seul piège : ses indices sont **décalés d'une colonne** par rapport à la
  numérotation d'openpyxl, d'où `DECALAGE_REGIONS`.
* **`Sources`** porte une citation complète et sa date pour chaque colonne —
  l'arrêté de protection avec son millésime, la liste rouge régionale avec ses
  auteurs et son année. C'est ce que BDC-Statuts ne donne pas sur la liste
  rouge européenne, et ici on l'a.
* **`MàJ`** donne qui le tient et depuis quand.

**Ce qu'il apporte au prédiagnostic.** Mesuré sur les 802 plantes de
Bédarieux : 749 listes rouges France, 213 listes rouges Europe, 6 protections
nationales et 2 régionales — là où le document sortait 802 lignes entièrement
vides. Et il écrit « Art. 1 », la nomenclature du livrable, quand BDC désigne
l'arrêté.

**Ce qu'il n'apporte pas.** Aucune colonne « déterminante ZNIEFF ». Ce n'est
pas un silence de sa part, c'est une question qu'il ne pose pas — d'où
`Reference.interroge()`, qui laisse BDC répondre là où le classeur n'a pas de
colonne du tout. Les colonnes d'espèces exotiques envahissantes et de
messicoles ne sont pas exposées : aucun type de BDC-Statuts ne leur
correspond, et aucune rubrique du prédiagnostic ne les attend encore.

**La colonne des zones humides l'est depuis le 8 novembre 2026.** « ZH
(Arrêté 2008) » marque « oui » les 807 taxons de la liste des espèces
indicatrices de l'arrêté du 24 juin 2008 (annexe 2.1). Aucun type de BDC ne
lui correspond non plus : elle prend le type `ZH`, que seule la rubrique
« Zone humide » interroge. On la cherche à son en-tête, et non à son rang :
elle est la dernière du classeur, la première à bouger quand une colonne
s'ajoute avant elle.
"""
from __future__ import annotations

import pickle
from pathlib import Path

import openpyxl

from .classeurs import Classeur, ColonneStatut, LigneTaxon, territoire_bdc

ONGLET_STATUTS = "TAXREF18"
ONGLET_REGIONS = "Régions"
ONGLET_SOURCES = "Sources"
ONGLET_MAJ = "MàJ"

#: Colonnes d'identification, en numérotation openpyxl (1 = première colonne).
COL_CD_REF, COL_NOM, COL_AUTEUR, COL_VERN = 1, 2, 3, 5

#: Colonnes de portée nationale : (colonne, champ, type BDC, territoire,
#: libellé). Le libellé compte pour la directive Habitats : le classeur y
#: écrit le **code espèce** (« 1674* »), et c'est l'en-tête qui dit à quelle
#: annexe — exactement comme dans les B-Statuts, que `_valeur_directive`
#: sait déjà rendre.
COLONNES_NATIONALES: tuple[tuple[int, str, str, str, str], ...] = (
    (11, "Ann. II DH", "DH", "France métropolitaine",
     "Annexe II directive Habitats"),
    (12, "PN", "PN", "France métropolitaine", "Protection nationale"),
    (42, "LRE", "LRE", "Europe", "Liste rouge Europe"),
    (43, "LRN", "LRN", "France métropolitaine", "Liste rouge France"),
)

#: La colonne des espèces indicatrices de zones humides (arrêté du 24 juin
#: 2008), reconnue à son en-tête. Type et territoire sont ceux qu'interroge
#: la rubrique « Zone humide » du prédiagnostic.
ENTETE_ZH = "ZH (Arrêté 2008)"
TYPE_ZH = "ZH"
TERRITOIRE_ZH = "France métropolitaine"

#: Version du cache, à monter quand ce qu'on lit du classeur change. La
#: signature du fichier n'y suffit pas : un cache écrit avant qu'on lise la
#: colonne ZH a la même, et le reprendre rendait une flore sans aucune
#: indicatrice — un silence qu'aucun message n'aurait signalé.
#:
#: 2 : la colonne des zones humides est lue (8 novembre 2026).
FORMAT_CACHE = 2

#: La feuille « Régions » numérote à partir de zéro là où openpyxl commence à
#: un. Vérifié sur les quatre familles de colonnes : elle annonce la
#: protection des Hauts-de-France en 12, et `PHdF` est la treizième colonne.
DECALAGE_REGIONS = 1

#: Valeurs qui veulent dire « rien ». **`0` en fait partie**, et ce n'est pas
#: un détail : la colonne des zones humides porte 11 452 zéros pour 807 « oui »,
#: et le prendre pour un statut aurait rempli le document de « 0 ».
_VIDES = {"", "0", "-", "none", "n/a"}


def _texte(valeur) -> str:
    brut = str(valeur).strip() if valeur is not None else ""
    return "" if brut.lower() in _VIDES else brut


def est_classeur_flore(chemin: Path) -> bool:
    """Reconnu à sa feuille, jamais à son nom de fichier.

    Il s'appelle « A - Statut FLORE.xlsx » aujourd'hui et s'appellera
    autrement demain. Ce qui ne changera pas, c'est qu'il porte une feuille
    `TAXREF18` là où les B-Statuts portent `Statuts`.
    """
    try:
        wb = openpyxl.load_workbook(chemin, read_only=True, data_only=True)
    except Exception:  # noqa: BLE001
        return False
    try:
        return ONGLET_STATUTS in wb.sheetnames
    finally:
        wb.close()


def _colonne_zh(wb) -> ColonneStatut | None:
    """La colonne « ZH (Arrêté 2008) », trouvée à son en-tête."""
    entete = next(wb[ONGLET_STATUTS].iter_rows(min_row=1, max_row=1,
                                               values_only=True), ())
    for numero, valeur in enumerate(entete, start=1):
        texte = str(valeur or "").strip()
        if texte.upper().startswith(TYPE_ZH):
            return ColonneStatut(
                index=numero, champ=texte, type_bdc=TYPE_ZH,
                territoire=TERRITOIRE_ZH, territoire_bdc=TERRITOIRE_ZH,
                libelle="Espèce indicatrice de zones humides (arrêté du "
                        "24 juin 2008)")
    return None


def _colonnes(wb) -> tuple[list[ColonneStatut], list[str]]:
    """Les colonnes exposées : les nationales, puis les régionales."""
    colonnes = [
        ColonneStatut(index=i, champ=champ, type_bdc=type_bdc,
                      territoire=terr, territoire_bdc=terr, libelle=libelle)
        for i, champ, type_bdc, terr, libelle in COLONNES_NATIONALES
    ]
    avertissements: list[str] = []
    zh = _colonne_zh(wb)
    if zh is not None:
        colonnes.append(zh)
    else:
        avertissements.append(
            f"Le classeur de flore n'a pas de colonne « {ENTETE_ZH} » : la "
            "flore indicatrice de zones humides n'est pas lue."
        )
    if ONGLET_REGIONS not in wb.sheetnames:
        avertissements.append(
            f"Le classeur de flore n'a pas de feuille « {ONGLET_REGIONS} » : "
            "seules ses colonnes nationales sont lues, les protections et "
            "listes rouges régionales sont ignorées."
        )
        return colonnes, avertissements

    for ligne in wb[ONGLET_REGIONS].iter_rows(min_row=2, max_col=5,
                                              values_only=True):
        region = _texte(ligne[0])
        if not region:
            continue
        vers = territoire_bdc(region)
        for brut, type_bdc, prefixe in ((ligne[1], "PR", "Protection"),
                                        (ligne[2], "LRR", "Liste rouge")):
            try:
                index = int(str(brut).strip()) + DECALAGE_REGIONS
            except (TypeError, ValueError):
                continue        # « - » : la région n'a pas de liste propre
            colonnes.append(ColonneStatut(
                index=index, champ=f"{type_bdc} {region}", type_bdc=type_bdc,
                territoire=region, territoire_bdc=vers,
                libelle=f"{prefixe} {region}",
            ))
    return colonnes, avertissements


def _citations(wb) -> dict[str, str]:
    """Code de colonne → référence bibliographique et date.

    C'est la feuille que BDC-Statuts n'a pas. Chaque liste rouge régionale y
    est citée avec ses auteurs et son année, chaque arrêté de protection avec
    sa date — de quoi satisfaire la Licence Ouverte sans rien reconstituer.
    """
    if ONGLET_SOURCES not in wb.sheetnames:
        return {}
    sortie: dict[str, str] = {}
    for ligne in wb[ONGLET_SOURCES].iter_rows(min_row=2, max_col=3,
                                              values_only=True):
        code, texte, date = (_texte(v) for v in ligne)
        if not code or not texte:
            continue
        annee = date[:4] if date[:4].isdigit() else ""
        sortie[code] = f"{texte} ({annee})" if annee else texte
    return sortie


def _edition(wb) -> str:
    """Qui le tient et depuis quand, d'après sa feuille « MàJ »."""
    if ONGLET_MAJ not in wb.sheetnames:
        return ""
    derniere = ""
    auteur = ""
    for ligne in wb[ONGLET_MAJ].iter_rows(min_row=2, max_col=3,
                                          values_only=True):
        qui, _, quand = (_texte(v) for v in ligne)
        if quand and quand[:10] > derniere:
            derniere, auteur = quand[:10], qui
    if not derniere:
        return ""
    jour = derniere[8:10], derniere[5:7], derniere[:4]
    return f"{auteur}, mise à jour du {'/'.join(jour)}" if auteur else \
        f"mise à jour du {'/'.join(jour)}"


def _taxons(wb, colonnes: list[ColonneStatut]) -> list[LigneTaxon]:
    """Une ligne par `CD_REF`, et non par nom.

    Le classeur porte les synonymes : 108 368 lignes pour 23 830 `CD_REF`.
    Leurs statuts sont les mêmes d'un synonyme à l'autre — vérifié, 19 cas
    seulement divergent, et chaque fois parce qu'une des lignes est vide. On
    garde donc **la ligne la plus renseignée** de chaque `CD_REF`, ce qui
    tranche ces dix-neuf cas dans le bon sens.
    """
    indices = sorted({c.index for c in colonnes})
    maxi = max(indices)
    retenus: dict[str, tuple[int, LigneTaxon]] = {}
    for numero, ligne in enumerate(
            wb[ONGLET_STATUTS].iter_rows(min_row=2, max_col=maxi,
                                         values_only=True), start=2):
        cd_ref = _texte(ligne[COL_CD_REF - 1])
        if not cd_ref:
            continue
        valeurs = {i: _texte(ligne[i - 1]) for i in indices
                   if _texte(ligne[i - 1])}
        precedent = retenus.get(cd_ref)
        if precedent is not None and len(precedent[1].valeurs) >= len(valeurs):
            continue
        retenus[cd_ref] = (numero, LigneTaxon(
            ligne=numero, cd_nom=cd_ref,
            nom_scientifique=_texte(ligne[COL_NOM - 1]),
            nom_commun=_texte(ligne[COL_VERN - 1]),
            auteur=_texte(ligne[COL_AUTEUR - 1]),
            valeurs=valeurs,
        ))
    return [taxon for _, taxon in retenus.values()]


def lire(chemin: Path, groupe: str = "flore",
         cache: Path | None = None) -> Classeur:
    """Lit le classeur de flore, depuis le cache quand il est à jour.

    La lecture complète prend 54 secondes — la feuille `TAXREF18` pèse 365 Mo
    décompressée. `charger_contexte` lit les classeurs à chaque démarrage :
    sans cache, l'outil mettrait une minute à s'ouvrir. La signature est la
    taille du fichier et sa date, comme pour les index TaxRef et BDC.
    """
    etat = chemin.stat()
    signature = f"{FORMAT_CACHE}-{etat.st_size}-{int(etat.st_mtime)}"
    if cache is not None and cache.exists():
        try:
            garde = pickle.loads(cache.read_bytes())
            if garde.get("signature") == signature:
                return Classeur(groupe=groupe, chemin=chemin,
                                taxons=garde["taxons"],
                                colonnes=garde["colonnes"],
                                avertissements=list(garde["avertissements"]),
                                citations=dict(garde["citations"]))
        except Exception:  # noqa: BLE001
            pass            # cache illisible ou d'une version antérieure

    wb = openpyxl.load_workbook(chemin, read_only=True, data_only=True)
    try:
        if ONGLET_STATUTS not in wb.sheetnames:
            raise ValueError(
                f"{chemin.name} n'a pas de feuille « {ONGLET_STATUTS} » : "
                "ce n'est pas un classeur de flore."
            )
        colonnes, avertissements = _colonnes(wb)
        citations = _citations(wb)
        edition = _edition(wb)
        taxons = _taxons(wb, colonnes)
    finally:
        wb.close()

    # **Une colonne vide d'un bout à l'autre n'est pas une réponse.** La
    # feuille `Régions` déclare une colonne de liste rouge pour l'Occitanie
    # et pour la Nouvelle-Aquitaine ; sa feuille `Sources` écrit « - » en
    # face, parce que ces listes n'existent pas, et les 23 830 cellules sont
    # vides. Les garder ferait taire BDC-Statuts au nom d'un silence qui
    # n'en est pas un — voir `Reference.interroge`.
    remplies = {index for taxon in taxons for index in taxon.valeurs}
    ignorees = [c.libelle for c in colonnes if c.index not in remplies]
    colonnes = [c for c in colonnes if c.index in remplies]
    if ignorees:
        avertissements.append(
            f"{len(ignorees)} colonne(s) du classeur de flore sont vides sur "
            f"toute sa hauteur et ne sont pas exposées : {', '.join(ignorees)}."
        )

    if edition:
        citations["_edition"] = edition
    classeur = Classeur(groupe=groupe, chemin=chemin, taxons=taxons,
                        colonnes=colonnes, avertissements=avertissements,
                        citations=citations)
    if cache is not None:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(pickle.dumps({
                "signature": signature, "taxons": taxons,
                "colonnes": colonnes, "avertissements": avertissements,
                "citations": citations,
            }))
        except Exception:  # noqa: BLE001
            pass            # un cache qu'on ne peut pas écrire n'est pas une
                            # raison de faire échouer la lecture
    return classeur
