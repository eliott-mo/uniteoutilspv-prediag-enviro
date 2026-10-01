"""Index TaxRef et moteur d'appariement nom → cd_ref.

Deux usages :

* **Veille** — résoudre les CD_NOM des classeurs B-Statuts : sont-ils valides,
  synonymes (CD_NOM ≠ CD_REF) ou supprimés ?
* **Recoupement** — apparier les noms que Marie récupère sur ses sources
  (exports, PDF, captures d'écran) vers un cd_ref unique.

Taux mesurés sur 360 espèces tirées de ses propres classeurs :

    nom scientifique            98,6 %
    nom commun + scientifique   95,8 %
    nom commun seul             85,3 %
    capture d'écran (OCR)       81,4 %

Deux règles font l'essentiel de la fiabilité :

* **filtre par groupe** — sans lui, « Grande Tortue » s'apparie à
  *Scutellaria galericulata*, une plante. Il ne gagne qu'un point de taux brut
  mais convertit des faux silencieux en « non résolu » explicites, ce qui est
  le bon échange : une question posée vaut mieux qu'une erreur invisible.
* **préférence de rang** — « Effraie des clochers » renvoie *Tyto alba* et deux
  sous-espèces ; on garde l'espèce.
"""
from __future__ import annotations

import csv
import difflib
import io
import pickle
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path

csv.field_size_limit(10 ** 7)

#: Change à chaque modification de la forme sérialisée (invalide les caches).
_FORMAT_CACHE = 2

# Groupes INPN (GROUP2_INPN) admis pour chaque classeur B-Statuts.
GROUPES_INPN: dict[str, set[str]] = {
    "oiseaux": {"Oiseaux"},
    "mammiferes": {"Mammifères"},
    "amphib-reptiles": {"Amphibiens", "Reptiles"},
    "insectes": {"Insectes", "Arachnides", "Crustacés", "Myriapodes", "Autres"},
    "macroheteroceres": {"Insectes"},
    "araignees": {"Arachnides"},
}

_BRUIT = re.compile(
    r"(?i)\b(male|femelle|juv|ad|imm|indetermine|indeterminee|indet|sp|spp|cf|total|especes?)\b\.?"
)
_ANNEE = re.compile(r"\b(1[89]|20)\d{2}\b")
_PARENTHESES = re.compile(r"\([^)]*\)")
_SEPARATEURS = (" - ", " – ", " — ", "/", ",", ";", "|")


def normaliser(s) -> str:
    """Minuscules, sans accents ni ponctuation — la forme de comparaison."""
    s = str(s or "").replace("’", " ").replace("‘", " ").replace("'", " ")
    s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode()
    s = s.lower().replace("-", " ")
    return re.sub(r"[^a-z0-9 ]", " ", re.sub(r"\s+", " ", s)).strip()


@dataclass
class Taxon:
    cd_nom: str
    cd_ref: str
    lb_nom: str          # nom scientifique porté par ce cd_nom
    nom_valide: str      # nom scientifique du cd_ref
    rang: str            # ES, SSES, GN…
    groupe: str          # GROUP2_INPN
    nom_vern: str = ""   # nom français de référence, pour les tableaux d'étude

    @property
    def est_synonyme(self) -> bool:
        return self.cd_ref != self.cd_nom

    @property
    def url(self) -> str:
        return f"https://inpn.mnhn.fr/espece/cd_nom/{self.cd_ref}"


@dataclass
class Appariement:
    statut: str              # exact | exact-sci | approche | ambigu | non resolu
    cd_ref: str | None
    info: str | None = None  # forme rapprochée, ou nombre de candidats

    @property
    def resolu(self) -> bool:
        return self.cd_ref is not None

    @property
    def sur(self) -> bool:
        """Appariement qu'on peut utiliser sans relecture humaine."""
        return self.statut in ("exact", "exact-sci")


class Index:
    """Index TaxRef chargé en mémoire, sérialisé pour les lancements suivants."""

    def __init__(self, taxons: dict[str, Taxon], vern: dict[str, list[str]],
                 sci: dict[str, list[str]], disparus: dict[str, tuple[str, str]],
                 version: str):
        self.taxons = taxons
        self.vern = vern
        self.sci = sci
        self.disparus = disparus
        self.version = version
        self._cles_vern = list(vern.keys())

    # ------------------------------------------------------------ construction

    @classmethod
    def construire(cls, archive: Path, membres: dict, version: str) -> "Index":
        z = zipfile.ZipFile(archive)
        taxons: dict[str, Taxon] = {}
        vern: dict[str, set[str]] = {}
        sci: dict[str, set[str]] = {}

        with z.open(membres["principal"]) as f:
            flux = io.TextIOWrapper(f, encoding="utf-8", errors="replace", newline="")
            for ligne in csv.DictReader(flux, delimiter="\t", quotechar='"'):
                cd = (ligne["CD_NOM"] or "").strip()
                if not cd:
                    continue
                ref = (ligne["CD_REF"] or "").strip() or cd
                taxons[cd] = Taxon(
                    cd_nom=cd, cd_ref=ref,
                    lb_nom=(ligne["LB_NOM"] or "").strip(),
                    nom_valide=(ligne["NOM_VALIDE"] or "").strip(),
                    rang=(ligne["RANG"] or "").strip(),
                    groupe=(ligne["GROUP2_INPN"] or "").strip(),
                    nom_vern=str(ligne["NOM_VERN"] or "").split(",")[0].strip(),
                )
                forme = normaliser(ligne["LB_NOM"])
                if forme:
                    sci.setdefault(forme, set()).add(ref)
                for bout in str(ligne["NOM_VERN"] or "").split(","):
                    forme = normaliser(bout)
                    if forme:
                        vern.setdefault(forme, set()).add(ref)

        # TAXVERN : noms vernaculaires alternatifs, un cd_nom pouvant en porter
        # plusieurs séparés par des virgules.
        with z.open(membres["vernaculaires"]) as f:
            flux = io.TextIOWrapper(f, encoding="utf-8", errors="replace", newline="")
            for ligne in csv.DictReader(flux, delimiter="\t", quotechar='"'):
                if (ligne.get("ISO639_3") or "").strip() != "fra":
                    continue
                cd = (ligne["CD_NOM"] or "").strip()
                ref = taxons[cd].cd_ref if cd in taxons else cd
                for bout in str(ligne["LB_VERN"] or "").split(","):
                    forme = normaliser(bout)
                    if forme:
                        vern.setdefault(forme, set()).add(ref)

        disparus: dict[str, tuple[str, str]] = {}
        with z.open(membres["disparus"]) as f:
            flux = io.TextIOWrapper(f, encoding="utf-8", errors="replace", newline="")
            for ligne in csv.DictReader(flux, delimiter="\t", quotechar='"'):
                disparus[(ligne["CD_NOM"] or "").strip()] = (
                    (ligne.get("CD_NOM_REMPLACEMENT") or "").strip(),
                    (ligne.get("RAISON_SUPPRESSION") or "").strip(),
                )

        return cls(taxons,
                   {k: sorted(v) for k, v in vern.items()},
                   {k: sorted(v) for k, v in sci.items()},
                   disparus, version)

    @classmethod
    def charger(cls, archive: Path, membres: dict, version: str,
                cache: Path | None = None) -> "Index":
        """Construit l'index, ou le relit depuis le cache s'il est à jour."""
        if cache and cache.exists():
            try:
                donnees = pickle.loads(cache.read_bytes())
                if (donnees.get("version") == version
                        and donnees.get("format") == _FORMAT_CACHE):
                    return cls(donnees["taxons"], donnees["vern"], donnees["sci"],
                               donnees["disparus"], version)
            except Exception:  # noqa: BLE001
                pass  # cache illisible ou d'une version antérieure du code

        index = cls.construire(archive, membres, version)
        if cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(pickle.dumps({
                "taxons": index.taxons, "vern": index.vern, "sci": index.sci,
                "disparus": index.disparus, "version": version,
                "format": _FORMAT_CACHE,
            }))
        return index

    # -------------------------------------------------------------- résolution

    def __len__(self) -> int:
        return len(self.taxons)

    def taxon(self, cd_nom: str) -> Taxon | None:
        return self.taxons.get(str(cd_nom).strip())

    def est_disparu(self, cd_nom: str) -> tuple[str, str] | None:
        return self.disparus.get(str(cd_nom).strip())

    def _filtrer_groupe(self, cds: list[str], groupe: str | None) -> list[str]:
        admis = GROUPES_INPN.get(groupe or "")
        if not admis:
            return cds
        retenus = [c for c in cds
                   if (self.taxons.get(c).groupe if c in self.taxons else "") in admis]
        # Aucun candidat du bon groupe : on ne force pas, l'appelant tranchera.
        return retenus

    def _preferer_espece(self, cds: list[str]) -> str | None:
        """Entre une espèce et ses sous-espèces de même nom, garder l'espèce."""
        if len(cds) == 1:
            return cds[0]
        especes = [c for c in cds
                   if c in self.taxons and self.taxons[c].rang == "ES"]
        return especes[0] if len(especes) == 1 else None

    def apparier(self, brut: str, groupe: str | None = None) -> Appariement:
        """Apparie un nom (vernaculaire ou scientifique) vers un cd_ref."""
        nettoye = _PARENTHESES.sub(" ", str(brut or ""))
        nettoye = _BRUIT.sub(" ", _ANNEE.sub(" ", nettoye)).strip(" ,;:.")
        if not normaliser(nettoye):
            return Appariement("non resolu", None, "vide après nettoyage")

        fragments = self._fragments(nettoye) + self._fragments(str(brut))
        for forme in fragments:
            for table, statut in ((self.vern, "exact"), (self.sci, "exact-sci")):
                if forme in table:
                    candidats = self._filtrer_groupe(table[forme], groupe)
                    if not candidats:
                        # Rien dans le groupe attendu : on refuse plutôt que de
                        # proposer une espèce d'un autre règne.
                        return Appariement("non resolu", None, "hors du groupe attendu")
                    cd = self._preferer_espece(candidats)
                    if cd:
                        return Appariement(statut, cd)
                    return Appariement("ambigu", None, f"{len(candidats)} candidats")

        forme = normaliser(nettoye)
        for proche in difflib.get_close_matches(forme, self._cles_vern, n=3, cutoff=0.88):
            candidats = self._filtrer_groupe(self.vern[proche], groupe)
            if not candidats:
                continue
            cd = self._preferer_espece(candidats)
            if cd:
                return Appariement("approche", cd, proche)
        return Appariement("non resolu", None)

    @staticmethod
    def _fragments(s: str) -> list[str]:
        """Chaîne entière, puis parties séparées — gère « Milan noir - Milvus migrans »."""
        bouts = [s]
        for sep in _SEPARATEURS:
            if sep in s:
                bouts += [p for p in s.split(sep) if p.strip()]
        vus, sortie = set(), []
        for b in bouts:
            forme = normaliser(b)
            if forme and forme not in vus:
                vus.add(forme)
                sortie.append(forme)
        return sortie
