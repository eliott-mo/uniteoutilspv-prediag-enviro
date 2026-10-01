"""Extraction des archives de l'INPN, qui suivent toutes le même motif.

Une archive publiée par l'INPN contient une seconde archive datée, qui contient
elle-même un dossier SIG (un shapefile par territoire : métropole, Guadeloupe,
Réunion…) et des CSV relationnels portant les attributs descriptifs.

    INPG.zip
      └── INPG_BDD_072025.zip
            ├── INPG_BDD_072025/SIG_INPG/inpg_sig_metrop.shp   ← géométries
            └── INPG_BDD_072025/inpg_data_site.csv.csv         ← libellés, texte

Les shapefiles sont extraits une fois dans un cache sur disque, parce que
geopandas ne sait pas lire au travers de deux niveaux de compression et que
réextraire 200 Mo à chaque interaction serait intenable dans une interface qui
relance son script à chaque clic.
"""
from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import geopandas as gpd

csv.field_size_limit(10 ** 7)

#: Extensions qui composent un shapefile. `.prj` est indispensable : sans lui
#: la projection est inconnue et le calcul de distance n'a aucun sens.
_COMPOSANTS = (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qmd")


#: Fragment permettant de choisir l'archive interne quand il y en a plusieurs.
#: Natura 2000 en livre deux : les données et, à côté, 73 Mo de fiches PDF.
_ZIP_DONNEES = ("bdd", "data", "sig")


def _ouvrir_imbriquee(chemin: Path) -> tuple[zipfile.ZipFile, zipfile.ZipFile | None]:
    """Ouvre l'archive et, le cas échéant, l'archive de données qu'elle contient.

    L'INPN emboîte presque toujours une archive datée dans l'archive publiée.
    Quand il y en a plusieurs, on prend celle des données : Natura 2000 livre
    `NATURA_BDD_122024.zip` et `NATURA_PDF_122024.zip`, et déballer 73 Mo de
    fiches PDF pour y chercher un shapefile serait du temps perdu.
    """
    externe = zipfile.ZipFile(chemin)
    zips = [n for n in externe.namelist() if n.lower().endswith(".zip")]
    autres = [n for n in externe.namelist()
              if not n.endswith("/") and not n.lower().endswith(".zip")]
    if not zips or autres:
        return externe, None
    if len(zips) == 1:
        choisi = zips[0]
    else:
        choisi = next((n for n in zips
                       if any(m in Path(n).stem.lower() for m in _ZIP_DONNEES)), zips[0])
    return externe, zipfile.ZipFile(io.BytesIO(externe.read(choisi)))


def _membres(chemin: Path) -> tuple[zipfile.ZipFile, list[str]]:
    externe, interne = _ouvrir_imbriquee(chemin)
    source = interne if interne is not None else externe
    return source, source.namelist()


def extraire_membre(chemin: Path, motif: str, cache: Path) -> Path:
    """Extrait un membre quelconque (GeoPackage, CSV volumineux…) vers le cache.

    Les espaces protégés sont livrés en GeoPackage — 148 Mo pour la métropole —
    que GDAL ne sait pas ouvrir à travers deux niveaux de compression.
    """
    source, noms = _membres(chemin)
    candidats = [n for n in noms if motif.lower() in n.lower() and not n.endswith("/")]
    if not candidats:
        raise FileNotFoundError(f"{chemin.name} : aucun membre « {motif} »")
    candidats.sort(key=len)
    membre = candidats[0]

    cache.mkdir(parents=True, exist_ok=True)
    cible = cache / Path(membre).name
    if cible.exists():
        return cible
    with source.open(membre) as flux, open(cible, "wb") as sortie:
        while True:
            bloc = flux.read(1 << 20)
            if not bloc:
                break
            sortie.write(bloc)
    return cible


def lister(chemin: Path, motif: str = "") -> list[str]:
    """Membres de l'archive, filtrés sur un fragment de nom (insensible à la casse)."""
    _, noms = _membres(chemin)
    bas = motif.lower()
    return sorted(n for n in noms if bas in n.lower())


def extraire_shapefile(chemin: Path, motif: str, cache: Path) -> Path:
    """Extrait le shapefile dont le nom contient `motif`, et renvoie son `.shp`.

    Le cache évite de réextraire : les archives pèsent jusqu'à 220 Mo et
    l'interface relance son script à chaque interaction.
    """
    source, noms = _membres(chemin)
    candidats = [n for n in noms if motif.lower() in n.lower() and n.lower().endswith(".shp")]
    if not candidats:
        disponibles = sorted({Path(n).name for n in noms if n.lower().endswith(".shp")})
        raise FileNotFoundError(
            f"{chemin.name} : aucun shapefile « {motif} ». Présents : "
            + (", ".join(disponibles[:12]) or "aucun")
        )
    if len(candidats) > 1:
        candidats.sort(key=len)
    membre = candidats[0]
    base = membre[: -len(".shp")]
    nom = Path(membre).stem

    cache.mkdir(parents=True, exist_ok=True)
    cible = cache / f"{nom}.shp"
    if cible.exists():
        return cible

    for extension in _COMPOSANTS:
        candidat = base + extension
        if candidat in noms:
            (cache / f"{nom}{extension}").write_bytes(source.read(candidat))
    if not cible.exists():
        raise FileNotFoundError(f"{chemin.name} : {membre} extrait sans son .shp")
    return cible


def charger_couche(chemin: Path, motif: str, cache: Path, crs: int = 2154,
                   couche: str | None = None) -> gpd.GeoDataFrame:
    """Couche de l'archive, reprojetée, géométries vides écartées.

    Accepte un shapefile ou un GeoPackage, selon le motif donné : l'INPN
    utilise les deux formats d'une base à l'autre.
    """
    if motif.lower().endswith(".gpkg") or ".gpkg" in motif.lower():
        fichier = extraire_membre(chemin, motif, cache)
        gdf = gpd.read_file(fichier, layer=couche) if couche else gpd.read_file(fichier)
    else:
        shp = extraire_shapefile(chemin, motif, cache)
        gdf = gpd.read_file(shp)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    if gdf.crs is None:
        raise ValueError(f"{shp.name} : projection absente (.prj manquant)")
    if gdf.crs.to_epsg() != crs:
        gdf = gdf.to_crs(crs)
    return gdf


#: Index déjà construits. Les tables descriptives se relisent à chaque
#: croisement et d'une source à l'autre — REF_ESPECE sert aux ZNIEFF de type I
#: puis à celles de type II —, pour un résultat identique.
_INDEX: dict[tuple, object] = {}


def lire_csv(chemin: Path, motif: str, colonnes: list[str] | None = None,
             cle: str | None = None) -> dict[str, dict[str, str]] | list[dict[str, str]]:
    """Lit un CSV de l'archive.

    Avec `cle`, renvoie un index `{valeur_de_clé: ligne}` — c'est la forme utile
    pour rattacher des attributs à des géométries. Sans, la liste des lignes.
    """
    empreinte = (str(chemin), motif, tuple(colonnes or ()), cle)
    if empreinte in _INDEX:
        return _INDEX[empreinte]

    source, noms = _membres(chemin)
    candidats = [n for n in noms
                 if motif.lower() in n.lower() and n.lower().endswith(".csv")]
    if not candidats:
        raise FileNotFoundError(f"{chemin.name} : aucun CSV « {motif} »")
    candidats.sort(key=len)

    with source.open(candidats[0]) as flux:
        texte = io.TextIOWrapper(flux, encoding="utf-8", errors="replace", newline="")
        echantillon = texte.read(8192)
        texte.seek(0) if texte.seekable() else None
        separateur = ";" if echantillon.count(";") >= echantillon.count(",") else ","
        # Le flux d'un zip n'est pas toujours rembobinable : on relit proprement.
        with source.open(candidats[0]) as flux2:
            texte2 = io.TextIOWrapper(flux2, encoding="utf-8", errors="replace",
                                      newline="")
            lecteur = csv.DictReader(texte2, delimiter=separateur)
            lignes = []
            index: dict[str, dict[str, str]] = {}
            for ligne in lecteur:
                garde = ({k: ligne.get(k, "") for k in colonnes}
                         if colonnes else dict(ligne))
                if cle:
                    valeur = (ligne.get(cle) or "").strip()
                    if valeur:
                        index[valeur] = garde
                else:
                    lignes.append(garde)
    resultat = index if cle else lignes
    _INDEX[empreinte] = resultat
    return resultat
