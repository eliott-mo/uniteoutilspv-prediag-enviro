"""Pré-diagnostic environnemental — tenue à jour des statuts et pré-remplissage.

Deux onglets, dans l'ordre où on s'en sert :

    A · Mise à jour des tables  — ce qui a bougé dans les référentiels depuis
                                  la dernière révision des classeurs UNITe
    B · Prédiag                 — emprise projet, communes, recoupement des
                                  sources d'espèces, tableaux Word

Ce que l'outil ne fait pas, et ne fera pas : écrire dans les classeurs, aller
chercher les occurrences à la place de l'experte, ou rédiger l'interprétation.
Il propose, elle arbitre.

Lancement :  streamlit run app.py
"""
from __future__ import annotations

import base64
import os
import shutil
import sys
import tempfile
from datetime import date
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

RACINE = Path(__file__).resolve().parent
sys.path.insert(0, str(RACINE / "src"))

from prediag_enviro import communes as mod_communes  # noqa: E402
from prediag_enviro import rapport as mod_rapport  # noqa: E402
from prediag_enviro import recoupement as mod_recoupement  # noqa: E402
from prediag_enviro import referentiels  # noqa: E402
from prediag_enviro import service, veille, vocabulaire  # noqa: E402
from prediag_enviro import zonages as mod_zonages  # noqa: E402
from prediag_enviro import cartes as mod_cartes  # noqa: E402
from prediag_enviro import extraits as mod_extraits  # noqa: E402
from prediag_enviro import chemins  # noqa: E402
from prediag_enviro import sources_locales as mod_sources  # noqa: E402
from prediag_enviro import rapport_prediag as mod_prediag  # noqa: E402
from prediag_enviro.memoire import ACCEPTE, A_REVOIR, DECISIONS, REFUSE  # noqa: E402

#: Le picto de l'outil, devant son titre et dans l'onglet du navigateur : les
#: outils UNITe portent tous le leur, et le chef de projet qui en ouvre
#: plusieurs les distingue dans sa barre d'onglets avant d'avoir lu un mot.
PICTO = "🦉"

#: Vert « couvert » et orange « partiel », repris de l'échelle de classement
#: partagée par extraction-topo-rge et pv-topo-analyzer. Ces deux teintes-là
#: se lisent aussi bien sur fond clair que sur fond sombre, ce qui compte :
#: l'app suit le thème Streamlit, donc celui du poste.
VERT_COUVERT = "#4CAF50"
ORANGE_PARTIEL = "#FF9800"

st.set_page_config(
    page_title="Prédiag environnemental", page_icon=PICTO, layout="wide"
)

# ── Logo UNITe — chargé une fois pour le header ───────────────────────────────
_logo_b64 = None
try:
    _logo_path = os.path.join(os.path.dirname(__file__), "logo_unite.png")
    with open(_logo_path, "rb") as _f:
        _logo_b64 = base64.b64encode(_f.read()).decode()
except FileNotFoundError:
    pass

# Header : titre à gauche, logo à droite
_col_titre, _col_logo = st.columns([8, 1], vertical_alignment="center")
with _col_titre:
    st.title(f"{PICTO} Prédiag environnemental")
    st.caption(
        "Tenue à jour des classeurs de statuts · Recoupement des sources "
        "d'espèces · Prédiagnostic écologique aux conventions UNITe"
    )
    st.caption(
        "Statuts et taxonomie : référentiels INPN figés, cités avec leur date. "
        "L'outil propose, vous arbitrez — les classeurs ne sont jamais modifiés."
    )
with _col_logo:
    if _logo_b64:
        st.markdown(
            f'<div style="text-align:right;">'
            f'<img src="data:image/png;base64,{_logo_b64}" '
            f'style="height:85px;max-width:100%;"></div>',
            unsafe_allow_html=True,
        )
st.divider()


# ── Chargements lourds, gardés entre deux interactions ────────────────────────
# Streamlit relance le script entier à chaque clic : sans cache, l'index TaxRef
# (708 685 taxons) serait reconstruit à chaque case cochée.
@st.cache_resource(show_spinner=False)
def _contexte() -> service.Contexte:
    zone = st.empty()
    ctx = service.charger_contexte(RACINE, progression=lambda m: zone.info(m))
    zone.empty()
    return ctx


@st.cache_resource(show_spinner="Lecture des classeurs UNITe…")
def _classeurs(_jeton: float):
    """`_jeton` force la relecture quand un classeur est redéposé."""
    return service.charger_classeurs(RACINE)


def _jeton_classeurs() -> float:
    """Empreinte de fraîcheur du dossier classeurs/."""
    return max((p.stat().st_mtime for p in chemins.classeurs().glob("*.xlsx")),
               default=0.0)


def _memoire():
    if "memoire" not in st.session_state:
        st.session_state.memoire = service.memoire_projet(RACINE)
    return st.session_state.memoire


def _aires_etude() -> list:
    """Les trois aires, telles que les sections 3 et 4 les emploient."""
    return [
        mod_zonages.AireEtude("ZIP", "Zone d'implantation potentielle", 0.0),
        mod_zonages.AireEtude("AEI", "Aire d'étude immédiate",
                              float(st.session_state.get("rayon_immediate", 200))),
        mod_zonages.AireEtude("AER", "Aire d'étude rapprochée",
                              float(st.session_state.get("rayon_rapprochee", 5000))),
    ]


def _nom_fichier(libelle: str) -> str:
    """Un nom de fichier sûr, tiré du nom des communes.

    Les noms de communes portent apostrophes, accents et virgules — « L'Isle-
    Adam, Mériel » — dont aucun n'a sa place dans un nom de fichier partagé
    entre Windows et OneDrive.
    """
    import re
    import unicodedata

    plat = unicodedata.normalize("NFD", libelle).encode("ascii", "ignore").decode()
    propre = re.sub(r"[^A-Za-z0-9]+", "-", plat).strip("-")
    return propre[:60] or "prediag"


def _dossier_travail() -> Path:
    """Dossier temporaire du dépôt courant, conservé le temps de la session."""
    if "dossier_travail" not in st.session_state:
        st.session_state.dossier_travail = Path(tempfile.mkdtemp(prefix="prediag_"))
    return st.session_state.dossier_travail


def _deposer(fichier) -> Path:
    cible = _dossier_travail() / fichier.name
    cible.write_bytes(fichier.getbuffer())
    return cible


@st.dialog("Carte", width="large")
def _agrandir(carte) -> None:
    """Montre une carte en grand, pour la contrôler avant de produire.

    Les planches sortent à 3 500 px de large. En vignette au quart de la page,
    les toponymes du fond de plan sont illisibles — or c'est précisément ce
    qu'on veut vérifier : qu'une commune mal cadrée ou un zonage mal placé se
    voit avant d'arriver dans le document.

    Le téléchargement reste proposé : même en pleine largeur, la boîte de
    dialogue n'affiche pas 3 500 px, et la lecture fine se fait dans une
    visionneuse.
    """
    st.markdown(f"**{carte.titre}** — {carte.nb_zonages} zonage(s)")
    st.image(str(carte.chemin), width="stretch")
    st.download_button(
        "⬇️ Télécharger en pleine définition", Path(carte.chemin).read_bytes(),
        file_name=Path(carte.chemin).name, mime="image/png", width="stretch",
        key=f"tel_{carte.famille}",
    )


service.emplacements(RACINE)
for _alerte in service.alertes_emplacements():
    st.warning(_alerte)

onglet_a, onglet_b = st.tabs([
    "A · Mise à jour des tables",
    "B · Prédiag",
])


# ══════════════════════════════════════════════════════════════════════════════
#  VOLET A — Mise à jour des tables
# ══════════════════════════════════════════════════════════════════════════════
with onglet_a:
    st.subheader("1 · État du référentiel")
    st.caption(
        "Quels référentiels INPN sont en place, et ce que vos classeurs "
        "donnent à comparer."
    )

    ctx = _contexte()
    cs = _classeurs(_jeton_classeurs())
    memoire = _memoire()

    col_etat, col_classeurs = st.columns([1, 2], gap="large")
    with col_etat:
        for citation in ctx.citations:
            st.caption(citation)
        st.caption(
            "Licence Ouverte (Etalab) — réutilisation libre, y compris "
            "commerciale, sous réserve de citer la source et sa date."
        )
        if st.button(
                "Vérifier s'il existe une version plus récente",
                help="Consulte la page de diffusion de l'INPN et compare à ce "
                     "que l'outil utilise. Les référentiels sont épinglés : "
                     "deux études faites à six mois d'écart restent comparables, "
                     "et changer de version est une décision, pas un effet de "
                     "bord.",
        ):
            with st.spinner("Consultation de l'INPN…"):
                etat, consulte = referentiels.comparer_versions(
                    service.lire_config(RACINE)
                )
            if not consulte:
                st.warning(
                    "Page de l'INPN injoignable — impossible de dire si une "
                    "version plus récente existe. Ce n'est pas « rien de neuf »."
                )
            else:
                retard = {c: v for c, v in etat.items() if v[0] != v[1]}
                if not retard:
                    st.success(
                        "À jour : "
                        + " · ".join(
                            f"{referentiels.NOMS_AFFICHES.get(c, c)} v{v[0]}"
                            for c, v in etat.items()
                        )
                    )
                else:
                    for cle, (epinglee, publiee) in retard.items():
                        nom = referentiels.NOMS_AFFICHES.get(cle, cle)
                        st.warning(
                            f"**{nom}** : l'outil utilise la v{epinglee}, "
                            f"l'INPN publie la v{publiee}."
                        )
                    st.caption(
                        "Pour basculer : mettre à jour `version` et `url` dans "
                        "`config/sources.yml`, puis relancer. Les études déjà "
                        "produites citent l'ancienne version — c'est voulu, "
                        "elles restent vérifiables en l'état."
                    )

    with col_classeurs:
        if not cs:
            st.warning(
                f"Aucun classeur dans `{chemins.classeurs()}`. Y déposer les "
                f"classeurs UNITe (noms de fichiers reconnus : "
                f"{', '.join(service.MOTIFS.values())})."
            )
        else:
            # Deux manques très différents se cachent derrière un même écart.
            #
            # Les colonnes de protection (PN, PR, DO) échappent partout, pour la
            # même raison de vocabulaire : c'est structurel, identique d'un
            # classeur à l'autre, et ça ne dit rien de la qualité de la veille.
            # Les colonnes périodisées, elles, n'échappent qu'aux oiseaux — et
            # là 38 listes rouges régionales sur 43 sortent du champ. C'est ce
            # manque-là qu'il faut voir.
            #
            # D'où le voyant : vert quand seules les protections manquent,
            # orange quand des listes rouges manquent aussi. Une règle « vert =
            # tout couvert » n'allumerait jamais le vert, et un voyant qui ne
            # change pas ne se regarde plus.
            lignes_couverture = []
            for groupe, cl in cs.items():
                typees = [c for c in cl.colonnes if c.type_bdc]
                confrontables = [c for c in typees
                                 if vocabulaire.comparable(c.type_bdc)]
                confrontees = [c for c in cl.colonnes if c.comparable]
                lignes_couverture.append({
                    "Classeur": groupe,
                    "Taxons": len(cl.taxons),
                    "Colonnes de statut": len(typees),
                    "Confrontées à BDC": len(confrontees),
                    "_complet": len(confrontees) == len(confrontables) and confrontables,
                })
            couverture = pd.DataFrame(lignes_couverture)
            complets = couverture.pop("_complet")

            # Couleurs reprises du parc (extraction-topo-rge, pv-topo-analyzer)
            # pour rester cohérent d'un outil à l'autre.
            def _teinte(colonne: pd.Series) -> list[str]:
                return [
                    f"color: {VERT_COUVERT if ok else ORANGE_PARTIEL};"
                    " font-weight: 600"
                    for ok in complets
                ]

            st.dataframe(
                couverture.style.apply(_teinte, subset=["Confrontées à BDC"]),
                hide_index=True, width="stretch",
                column_config={
                    "Classeur": st.column_config.TextColumn(
                        help="Le classeur UNITe lu dans `classeurs/`, un par "
                             "groupe taxonomique."),
                    "Taxons": st.column_config.NumberColumn(
                        format="%d",
                        help="Lignes de l'onglet « Statuts » : espèces, mais "
                             "aussi sous-espèces et populations évaluées à part."),
                    "Colonnes de statut": st.column_config.NumberColumn(
                        format="%d",
                        help="Colonnes dont le type est reconnu : listes rouges, "
                             "protections, directives, ZNIEFF déterminantes."),
                    "Confrontées à BDC": st.column_config.NumberColumn(
                        format="%d",
                        help="Celles que la veille compare réellement. En vert : "
                             "seules les colonnes de protection échappent, ce qui "
                             "est le cas partout (BDC désigne l'arrêté, le "
                             "classeur l'article). En orange : des listes rouges "
                             "échappent aussi, faute de pouvoir rattacher une "
                             "période — BDC ne distingue pas nicheurs, hivernants "
                             "et de passage."),
                },
            )
            st.caption(
                f"<span style='color:{VERT_COUVERT};font-weight:600'>Vert</span> : "
                "il ne manque que les colonnes de protection, ce qui est le cas "
                "partout. "
                f"<span style='color:{ORANGE_PARTIEL};font-weight:600'>Orange</span> : "
                "des listes rouges manquent aussi. Seul le classeur oiseaux est "
                "dans ce cas — 38 de ses 43 colonnes régionales sont "
                "périodisées. BDC porte bien la période — dans RQ_STATUT pour "
                "les listes nationales, dans le titre du document cité pour "
                "les régionales — mais la veille ne l'exploite pas encore.",
                unsafe_allow_html=True,
            )

    if cs:
        st.divider()
        st.subheader("2 · Vérifier ce qui a bougé")
        st.caption(
            "Confronte vos classeurs à TaxRef et BDC-Statuts. Restreignez "
            "aux groupes et aux territoires de l'étude à venir, ou laissez "
            "tout pour une revue complète."
        )

        col_g, col_t, col_b = st.columns([2, 2, 1], gap="large")
        with col_g:
            groupes = st.multiselect("Groupes", list(cs), default=list(cs))
        with col_t:
            # Liste plutôt que saisie libre : le nom d'une région diffère entre
            # le classeur et BDC (« Centre-Val de Loire » contre « Centre »), et
            # une saisie qui ne correspond à rien renvoyait les statuts
            # nationaux — ce qui ressemblait à un résultat.
            territoires = st.multiselect(
                "Territoires", service.territoires_disponibles(cs, ctx.statuts),
                placeholder="Tous les territoires",
                help="Régions que BDC-Statuts couvre pour vos classeurs, "
                     "écrites comme BDC les écrit. Les listes rouges nationale "
                     "et européenne remontent de toute façon.",
            )
        with col_b:
            st.write("")
            lancer = st.button("Vérifier", type="primary", width="stretch")

        if lancer:
            with st.spinner("Comparaison aux référentiels…"):
                res, masques = service.lancer_veille(
                    ctx, cs, memoire, groupes=groupes or None,
                    territoires=territoires or None,
                )
            st.session_state.veille = res
            st.session_state.veille_masques = masques

        res = st.session_state.get("veille")
        if res is not None:
            masques = st.session_state.get("veille_masques", 0)
            st.divider()
            st.subheader("3 · Arbitrer")
            st.caption(
                "Ce qui diffère, par nature de constat. Renseignez la colonne "
                "Décision : un refus est retenu lui aussi, et le constat ne "
                "reviendra que si la source rebouge."
            )

            mesures = st.columns(4)
            for colonne, (cle, titre) in zip(mesures, veille.FAMILLES):
                colonne.metric(titre.split(" ", 1)[1], len(res.par_famille(cle)))
            mesures[3].metric("Déjà arbitrés", masques,
                              help="Constats masqués parce que vous les avez déjà "
                                   "tranchés et que la source n'a pas rebougé.")

            for avertissement in res.avertissements:
                st.caption(f"ℹ️ {avertissement}")

            arbitrages: dict[str, tuple[str, str]] = {}
            for cle, titre in veille.FAMILLES:
                constats = res.par_famille(cle)
                if not constats:
                    continue
                st.markdown(f"**{titre}** — {len(constats)} ligne(s)")
                cadre = pd.DataFrame([{
                    "Décision": "",
                    "Groupe": c.groupe,
                    "Ligne": c.ligne,
                    "Taxon": c.taxon,
                    "Champ": c.champ,
                    "Actuel": c.actuel,
                    "Proposé": c.propose,
                    "Détail": c.detail,
                    "Vérifier": c.lien,
                    "Note": "",
                } for c in constats])
                edite = st.data_editor(
                    cadre, hide_index=True, width="stretch", key=f"ed_{cle}",
                    column_config={
                        "Décision": st.column_config.SelectboxColumn(
                            options=list(DECISIONS), width="small"),
                        "Vérifier": st.column_config.LinkColumn(
                            display_text="ouvrir", width="small"),
                        "Note": st.column_config.TextColumn(width="medium"),
                        "Ligne": st.column_config.NumberColumn(format="%d", width="small"),
                    },
                    disabled=["Groupe", "Ligne", "Taxon", "Champ", "Actuel",
                              "Proposé", "Détail", "Vérifier"],
                )
                for constat, (_, ligne) in zip(constats, edite.iterrows()):
                    decision = str(ligne["Décision"] or "").strip()
                    if decision in DECISIONS:
                        arbitrages[constat.cle] = (decision, str(ligne["Note"] or ""),
                                                   constat.propose)

            col_enr, col_tel = st.columns([1, 1], gap="large")
            with col_enr:
                if st.button(f"Enregistrer {len(arbitrages)} arbitrage(s)",
                             type="primary", width="stretch",
                             disabled=not arbitrages):
                    for cle_constat, (decision, note, propose) in arbitrages.items():
                        memoire.trancher(cle_constat, decision, propose, note)
                    memoire.enregistrer()
                    st.success(
                        f"{len(arbitrages)} arbitrage(s) enregistré(s). Les "
                        "constats refusés ne reviendront que si la source rebouge."
                    )
                    st.session_state.pop("veille", None)
                    st.rerun()
            with col_tel:
                tampon = _dossier_travail() / f"veille_{date.today().isoformat()}.xlsx"
                mod_rapport.ecrire(res, tampon, ctx.citations, memoire)
                st.download_button(
                    "⬇️ Télécharger le rapport Excel", tampon.read_bytes(),
                    file_name=tampon.name, width="stretch",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                st.caption(
                    "Même contenu que ci-dessus, au format de l'onglet « Suivi "
                    "modifs statuts » de vos classeurs. Annoté, il se relit avec "
                    "`python run_veille.py --relire`."
                )

    # ── Extraits départementaux ───────────────────────────────────────────
    # Même rituel que la mise à jour des classeurs : on vient ici quand l'INPN
    # publie, et on reconstruit ce que toute l'équipe utilisera.
    st.divider()
    st.subheader("4 · Extraits départementaux")
    st.caption(
        "Les zonages découpés par département, que les chefs de projet "
        "utilisent pour leurs prédiags. Seul ce poste porte les 462 Mo "
        "d'archives nationales qui servent à les produire."
    )

    etat_ext = service.etat_extraits(RACINE)
    cfg_sources = service.lire_config(RACINE)
    versions_zonages = {c: spec["version"]
                        for c, spec in cfg_sources["referentiels"].items()
                        if c in service.CLES_ZONAGES}

    col_etat_e, col_act_e = st.columns([2, 1], gap="large")
    with col_etat_e:
        if etat_ext is None:
            st.warning(
                "Aucun extrait construit. Les chefs de projet ne pourront pas "
                "produire de prédiag tant qu'ils n'existent pas."
            )
        else:
            perimes = etat_ext.perime(versions_zonages)
            if perimes:
                st.warning(
                    f"{etat_ext.nombre} département(s), construits le "
                    f"{etat_ext.construit_le}. **À reconstruire** : "
                    + ", ".join(referentiels.NOMS_AFFICHES.get(c, c)
                                for c in perimes)
                    + " a changé de version depuis."
                )
            else:
                st.success(
                    f"{etat_ext.nombre} département(s), construits le "
                    f"{etat_ext.construit_le} — à jour."
                )
            st.caption("Versions utilisées : " + " · ".join(
                f"{referentiels.NOMS_AFFICHES.get(c, c)} {v}"
                for c, v in etat_ext.versions.items()))

    with col_act_e:
        st.write("")
        if st.button("Reconstruire les extraits", width="stretch",
                     key="btn_extraits"):
            zone_e = st.empty()
            barre = st.progress(0.0)
            total = len(mod_extraits.departements_metropole())

            def _avancer(message: str) -> None:
                zone_e.info(message)
                if "/" in message:
                    try:
                        fait = int(message.split("(")[1].split("/")[0])
                        barre.progress(min(fait / total, 1.0))
                    except Exception:  # noqa: BLE001
                        pass

            try:
                service.construire_extraits(RACINE, progression=_avancer)
                barre.progress(1.0)
                st.success("Extraits reconstruits.")
                st.rerun()
            except Exception as erreur:  # noqa: BLE001
                st.error(f"Construction impossible : {erreur}")

    st.caption(
        "Comptez **environ trois quarts d'heure** pour les 96 départements — "
        "mesuré, à deux départements par minute —, puis le temps que OneDrive "
        "téléverse les quelque 650 Mo produits. C'est une opération qu'on "
        "lance et qu'on laisse tourner, pas un clic entre deux réunions. "
        "À faire quand le bouton de vérification de version signale du neuf, "
        "pas plus souvent : les référentiels INPN sortent une à deux fois par an."
    )


    st.divider()
    st.subheader("5 · Couches sans source nationale")
    st.caption(
        "Les espaces naturels sensibles n'ont pas de couche nationale fiable : "
        "ils relèvent du Département ou de la région, et la couche nationale de "
        "l'INPN est diffusée comme « en construction ». Ce que vous trouvez se "
        "dépose ici une fois, et sert à tous les projets suivants du même "
        "département."
    )

    connues = mod_sources.registre()
    if connues:
        lignes = [{
            "Département": departement,
            "Type": source.type_libelle,
            "Source": source.libelle,
            "Lien": source.url,
            "Consultée le": source.consulte_le,
            "Couche": "oui" if source.fichier else "—",
            "Déposée par": source.par,
        } for departement in sorted(connues) for source in connues[departement]]
        st.dataframe(pd.DataFrame(lignes), hide_index=True, width="stretch")
    else:
        st.caption(
            "Aucune source enregistrée pour l'instant. Tant qu'un département "
            "n'en a pas, le prédiagnostic le dit explicitement plutôt que de "
            "laisser croire qu'il n'y a pas de zonage."
        )

    with st.form("depot_source_locale"):
        col_dep, col_type = st.columns(2)
        with col_dep:
            departement = st.text_input(
                "Département", max_chars=3,
                help="Code INSEE : 76, 2A… Une couche régionale se dépose "
                     "pour chacun des départements qu'elle couvre.")
        with col_type:
            type_libelle = st.selectbox(
                "Type de zonage",
                ["Espace Naturel Sensible", "Réserve naturelle régionale",
                 "Parc naturel régional", "Autre"])
        libelle = st.text_input(
            "Intitulé de la source",
            placeholder="Espaces naturels sensibles du Département de …",
            help="Ce libellé partira en bibliographie du prédiagnostic.")
        url = st.text_input("Lien (optionnel)",
                            placeholder="https://…")
        couche = st.file_uploader(
            "Couche (optionnelle)", type=["zip", "geojson", "json", "gpkg", "kml"],
            help="ZIP d'un shapefile, GeoJSON, GeoPackage ou KML. Sans couche, "
                 "la source est seulement citée en bibliographie — utile quand "
                 "vous avez consulté un visualiseur sans export.")
        avertissement = st.text_input(
            "Avertissement (optionnel)",
            placeholder="couche en construction, non exhaustive…",
            help="S'affichera dans le prédiagnostic sous le tableau. À "
                 "renseigner dès que la source se sait incomplète.")
        enregistrer = st.form_submit_button("Enregistrer la source",
                                            type="primary")

    if enregistrer:
        if not departement.strip() or not libelle.strip():
            st.warning("Le département et l'intitulé sont nécessaires : sans "
                       "eux la source ne pourrait être ni retrouvée ni citée.")
        else:
            try:
                if couche is not None:
                    source = mod_sources.deposer(
                        _deposer(couche), departement=departement.strip(),
                        type_libelle=type_libelle, libelle=libelle.strip(),
                        url=url.strip())
                else:
                    source = mod_sources.Source(
                        departement=departement.strip(),
                        type_libelle=type_libelle, libelle=libelle.strip(),
                        url=url.strip())
                    mod_sources.enregistrer(source)
                if avertissement.strip():
                    source.avertissement = avertissement.strip()
                    mod_sources.enregistrer(source)
                st.success(
                    f"{source.type_libelle} · {source.libelle} enregistrée "
                    f"pour le {source.departement}."
                    + (" La couche sera croisée avec l'emprise des prochains "
                       "projets de ce département." if source.fichier else
                       " Sans couche, elle sera citée en bibliographie.")
                )
                st.rerun()
            except Exception as erreur:  # noqa: BLE001
                st.error(f"Dépôt impossible : {erreur}")


# ══════════════════════════════════════════════════════════════════════════════
#  VOLET B — Prédiag
# ══════════════════════════════════════════════════════════════════════════════
with onglet_b:
    st.subheader("1 · Périmètre du projet")
    st.caption(
        "Charge la zone d'implantation potentielle et la contrôle avant tout "
        "calcul. Archive ZIP d'un shapefile complet (`.shp`, `.shx`, `.dbf`, "
        "`.prj`), ou fichier KML / GeoJSON."
    )

    depot_emprise = st.file_uploader(
        "Périmètre", type=["zip", "kml", "geojson", "json"],
        label_visibility="collapsed",
    )
    if depot_emprise is not None:
        # Streamlit relance le script à chaque interaction : sans cette garde,
        # l'emprise serait réécrite et re-analysée à chaque case cochée.
        empreinte = (depot_emprise.name, depot_emprise.size)
        if st.session_state.get("empreinte_emprise") != empreinte:
            try:
                st.session_state.emprise = mod_communes.charger_emprise(
                    _deposer(depot_emprise)
                )
                st.session_state.empreinte_emprise = empreinte
                # Le découpage portait sur l'emprise précédente.
                st.session_state.pop("decoupage", None)
            except Exception as erreur:  # noqa: BLE001
                st.session_state.pop("emprise", None)
                st.session_state.pop("empreinte_emprise", None)
                st.error(f"Lecture impossible : {erreur}")

    emprise = st.session_state.get("emprise")
    if emprise is not None:
        # Le contrôle d'entrée passe avant tout calcul : une erreur de
        # projection doit se voir ici, pas trois étapes plus loin.
        for ligne in emprise.controle():
            (st.warning if ligne.startswith("⚠") else st.caption)(ligne)

        st.divider()
        st.subheader("2 · Communes concernées")
        st.caption(
            "Les communes que l'emprise touche, avec leur part de surface. "
            "C'est sur elles que portera la recherche d'espèces."
        )

        if "decoupage" not in st.session_state:
            with st.spinner("Intersection avec les contours communaux…"):
                st.session_state.decoupage = mod_communes.communes_concernees(
                    emprise, cache=chemins.referentiels()
                )
        decoupage = st.session_state.decoupage

        for avertissement in decoupage.avertissements:
            st.caption(f"ℹ️ {avertissement}")

        if decoupage.communes:
            cadre = pd.DataFrame([{
                "Retenue": c.retenue, "Code INSEE": c.code, "Commune": c.nom,
                "Part de l'emprise": c.part, "Surface (ha)": round(c.surface_ha, 2),
            } for c in decoupage.communes])
            edite = st.data_editor(
                cadre, hide_index=True, width="stretch", key="ed_communes",
                column_config={
                    "Retenue": st.column_config.CheckboxColumn(width="small"),
                    "Part de l'emprise": st.column_config.ProgressColumn(
                        format="%.1f %%", min_value=0.0, max_value=1.0),
                },
                disabled=["Code INSEE", "Commune", "Part de l'emprise", "Surface (ha)"],
            )
            for commune, (_, ligne) in zip(decoupage.communes, edite.iterrows()):
                commune.retenue = bool(ligne["Retenue"])
            st.caption(
                "Une commune effleurée ne justifie pas forcément une recherche "
                "d'espèces — à vous de la décocher."
            )

        col_insee, col_ajout = st.columns([3, 1], gap="large")
        with col_insee:
            code_manuel = st.text_input(
                "Ajouter une commune par code INSEE", placeholder="76561",
                help="Si la détection a échoué, ou pour inclure une commune "
                     "limitrophe que vous jugez pertinente.",
            )
        with col_ajout:
            st.write("")
            if st.button("Ajouter", width="stretch", disabled=not code_manuel.strip()):
                ajoutee = mod_communes.commune_par_code(code_manuel.strip())
                if ajoutee is None:
                    st.error(f"Code INSEE {code_manuel} inconnu.")
                elif any(c.code == ajoutee.code for c in decoupage.communes):
                    st.info(f"{ajoutee.libelle} est déjà dans la liste.")
                else:
                    decoupage.communes.append(ajoutee)
                    st.rerun()

        st.divider()
        st.subheader("3 · Aires d'étude")
        st.caption(
            "Les périmètres autour de l'emprise dans lesquels les enjeux seront "
            "recherchés. Rayons par défaut d'après le guide du ministère (2016), "
            "à ajuster selon le projet."
        )
        col_imm, col_rap = st.columns(2, gap="large")
        with col_imm:
            st.number_input("Aire d'étude immédiate (m)", 0, 5000,
                            st.session_state.get("rayon_immediate", 200), step=50,
                            key="rayon_immediate")
        with col_rap:
            st.number_input("Aire d'étude rapprochée (m)", 0, 30000,
                            st.session_state.get("rayon_rapprochee", 5000), step=500,
                            key="rayon_rapprochee")


        st.divider()
        st.subheader("4 · Zonages du patrimoine naturel")
        st.caption(
            "ZNIEFF, Natura 2000, espaces protégés et patrimoine géologique "
            "présents dans les aires d'étude, avec leur distance à la ZIP et "
            "leur intérêt. Rien à saisir : tout vient des référentiels INPN."
        )

        departements = service.departements_de(decoupage)
        etat_ext = service.etat_extraits(RACINE)
        if departements:
            st.caption(
                "Département(s) du projet : " + ", ".join(departements)
                + (f" · {etat_ext.nombre} extrait(s) disponible(s)"
                   if etat_ext else " · aucun extrait, lecture des archives "
                                    "nationales")
            )

        if st.button("Croiser les zonages", type="primary", width="stretch",
                     key="btn_zonages"):
            zone = st.empty()
            try:
                with st.spinner("Croisement…"):
                    if etat_ext is not None and departements:
                        # Voie normale : les extraits départementaux, quelques
                        # mégaoctets au lieu des 462 Mo d'archives nationales.
                        st.session_state.zonages = (
                            service.croiser_zonages_extraits(
                                RACINE, emprise.union, departements,
                                aires=_aires_etude())
                        )
                    else:
                        # Repli : le poste qui tient les référentiels à jour
                        # porte les archives et peut s'en servir directement.
                        st.session_state.zonages = service.croiser_zonages(
                            RACINE, emprise.union, aires=_aires_etude(),
                            progression=lambda m: zone.info(m))
            except mod_extraits.DepartementAbsent as manque:
                st.error(str(manque))
                st.caption(
                    "L'outil refuse plutôt que de rendre une liste vide : un "
                    "prédiag qui annonce « aucun zonage » faute de données "
                    "serait faux, et rien ne le signalerait à la lecture."
                )
            except Exception as erreur:  # noqa: BLE001
                st.error(f"Croisement impossible : {erreur}")
            zone.empty()

        resultat_zonages = st.session_state.get("zonages")
        if resultat_zonages is not None:
            st.info(resultat_zonages.resume())
            for manquant in resultat_zonages.manquants:
                st.warning(manquant)

            for famille, titre in mod_zonages.FAMILLES:
                trouves = resultat_zonages.par_famille(famille)
                if not trouves:
                    continue
                st.markdown(f"**{titre}** — {len(trouves)}")
                st.dataframe(
                    pd.DataFrame([{
                        "Nom": z.nom,
                        "Distance à la ZIP": z.distance_lisible,
                        "Type": z.type,
                        "Identifiant": z.identifiant,
                        "Aires": ", ".join(z.aires),
                        "Intérêt": z.interet,
                    } for z in trouves]),
                    hide_index=True, width="stretch",
                    column_config={
                        "Intérêt": st.column_config.TextColumn(width="large"),
                        "Nom": st.column_config.TextColumn(width="medium"),
                    },
                )
            st.caption(
                "Les noms que les référentiels portent tout en capitales sont "
                "remis en casse de lecture — « FORET D'ARGONNE AU NORD DE L'A4 » "
                "devient « Forêt d'Argonne au nord de l'A4 ». Les particules et "
                "les noms communs de géographie passent en bas de casse, le "
                "reste garde sa capitale ; un nom commun rare peut donc en "
                "prendre une de trop. Les noms déjà écrits en casse mixte ne "
                "sont jamais retouchés."
            )

            st.markdown("**Cartes**")
            st.caption(
                "Une carte par famille, A4 paysage, cadrée sur l'aire d'étude "
                "rapprochée — une seule carte pour les trois familles donnerait "
                "un empilement illisible dès qu'elles se recouvrent, ce qui est "
                "le cas général en vallée alluviale."
            )
            if st.button("Produire les cartes", width="stretch", key="btn_cartes"):
                with st.spinner("Rendu des cartes…"):
                    try:
                        st.session_state.cartes = mod_cartes.produire(
                            resultat_zonages, emprise.gdf,
                            _aires_etude(), _dossier_travail() / "cartes",
                            ", ".join(c.nom for c in decoupage.retenues)
                            or "Zone d'étude",
                        )
                    except Exception as erreur:  # noqa: BLE001
                        st.error(f"Rendu impossible : {erreur}")

            produites = st.session_state.get("cartes") or []
            if produites:
                # Les planches sur une seule ligne. Empilées en pleine largeur,
                # elles repoussaient les sections suivantes plusieurs écrans
                # plus bas : la vignette suffit à juger du cadrage et du nombre
                # de zonages, « Agrandir » sert à lire le détail.
                for colonne, carte in zip(st.columns(len(produites)), produites):
                    with colonne:
                        st.image(str(carte.chemin), width="stretch")
                        st.caption(f"{carte.titre} — "
                                   f"{carte.nb_zonages} zonage(s)")
                        if st.button("Agrandir", width="stretch",
                                     key=f"zoom_{carte.famille}"):
                            _agrandir(carte)
                st.caption(
                    "Fond Plan IGN (Géoplateforme). Le serveur de tuiles public "
                    "d'OpenStreetMap refuse l'usage automatisé : sa politique "
                    "l'interdit, et on ne la contourne pas."
                )
        st.divider()
        st.subheader("5 · Sources d'espèces")
        st.caption(
            "Ce qu'on attend ici est la **liste des espèces** présentes, et "
            "elle seule : leurs statuts sont lus automatiquement dans "
            "BDC-Statuts, et les classeurs UNITe ne servent qu'à la veille "
            "de l'onglet A — rien à charger de ce côté. Déposez donc ce que "
            "vous avez relevé sur vos sources ; l'outil les recoupe, il ne va "
            "rien chercher à votre place. Sans dépôt, les volets Avifaune, "
            "Chiroptères et Autre faune du document sortent sans tableau. "
            "Exports Excel ou CSV, PDF, captures d'écran — un export avec les "
            "noms latins vaut dix captures : 98,6 % d'appariement contre 81 %."
        )

        depots_sources = st.file_uploader(
            "Sources", accept_multiple_files=True, label_visibility="collapsed",
            type=["xlsx", "xlsm", "xls", "csv", "tsv", "txt", "pdf",
                  "png", "jpg", "jpeg", "tif", "tiff", "webp"],
        )

        if depots_sources:
            codes = [c.code for c in decoupage.retenues] or [""]
            groupes_connus = list(service.MOTIFS)
            lignes = []
            for fichier in depots_sources:
                nom = fichier.name.lower()
                # Les trois étiquettes sont devinées du nom de fichier quand
                # c'est possible : « ODIN_oiseaux_76561.xlsx » se range seul.
                groupe = next((g for g in groupes_connus if g.split("-")[0] in nom), groupes_connus[0])
                code = next((c for c in codes if c and c in nom), codes[0])
                lignes.append({
                    "Fichier": fichier.name, "Commune": code, "Groupe": groupe,
                    "Source": Path(fichier.name).stem.split("_")[0],
                })
            etiquettes = st.data_editor(
                pd.DataFrame(lignes), hide_index=True, width="stretch",
                key="ed_sources",
                column_config={
                    "Commune": st.column_config.SelectboxColumn(options=codes),
                    "Groupe": st.column_config.SelectboxColumn(options=groupes_connus),
                    "Source": st.column_config.TextColumn(
                        help="Nom qui apparaîtra dans le document : "
                             "faune-normandie, ODIN…"),
                },
                disabled=["Fichier"],
            )

            if st.button("Recouper les sources", type="primary", width="stretch"):
                ctx = _contexte()
                depots = [
                    mod_recoupement.Depot(
                        chemin=_deposer(fichier),
                        commune=str(ligne["Commune"]), groupe=str(ligne["Groupe"]),
                        source=str(ligne["Source"]),
                    )
                    for fichier, (_, ligne) in zip(depots_sources, etiquettes.iterrows())
                ]
                with st.spinner("Appariement sur TaxRef…"):
                    st.session_state.recoupement = mod_recoupement.consolider(
                        depots, ctx.index, _memoire()
                    )

        resultat = st.session_state.get("recoupement")
        if resultat is not None:
            st.divider()
            st.subheader("6 · Liste recoupée")
            st.caption(
                "Vos sources fondues en une liste unique, dédoublonnée par "
                "taxon. Les noms que TaxRef n'a pas reconnus sont isolés plus "
                "bas, à corriger une fois pour toutes."
            )

            col_e, col_n, col_t = st.columns(3)
            col_e.metric("Espèces", len(resultat.especes))
            col_n.metric("Non résolus", len(resultat.non_resolus))
            col_t.metric("Taux de résolution", f"{resultat.taux_resolution:.0%}")

            for ligne in resultat.journal:
                st.caption(ligne)

            if resultat.especes:
                st.dataframe(
                    pd.DataFrame([{
                        "Nom commun": e.nom_commun,
                        "Nom scientifique": e.nom_scientifique,
                        "Nidification": e.nidification,
                        "Dernière observation": e.date_obs,
                        "Sources": ", ".join(e.sources),
                        "Communes": ", ".join(e.communes),
                        "Conflits": " · ".join(e.conflits),
                        "Fiche INPN": e.url,
                    } for e in resultat.especes]),
                    hide_index=True, width="stretch",
                    column_config={"Fiche INPN": st.column_config.LinkColumn(
                        display_text="ouvrir", width="small")},
                )

            if resultat.non_resolus:
                st.markdown("**Non résolus** — à corriger à la main")
                st.caption(
                    "TaxRef sert de correcteur : un nom mal lu ne s'apparie pas "
                    "et atterrit ici plutôt que de passer inaperçu. Une fois "
                    "corrigé, l'outil retient l'association pour les prochaines "
                    "études."
                )
                cadre = pd.DataFrame([{
                    "Nom reçu": m.nom_brut, "Source": m.depot.source,
                    "Groupe": m.depot.groupe, "Nom corrigé": "",
                } for m in resultat.non_resolus])
                corrige = st.data_editor(
                    cadre, hide_index=True, width="stretch", key="ed_nonresolus",
                    disabled=["Nom reçu", "Source", "Groupe"],
                )
                corrections: dict[str, str] = {}
                ctx = _contexte()
                for mention, (_, ligne) in zip(resultat.non_resolus, corrige.iterrows()):
                    propose = str(ligne["Nom corrigé"] or "").strip()
                    if not propose:
                        continue
                    appariement = ctx.index.apparier(propose, mention.depot.groupe)
                    if appariement.resolu:
                        corrections[mention.nom_brut] = appariement.cd_ref
                if corrections and st.button(
                        f"Apprendre {len(corrections)} correspondance(s)",
                        width="stretch"):
                    mod_recoupement.apprendre(resultat, corrections, _memoire())
                    st.success(
                        f"{len(corrections)} correspondance(s) retenue(s). "
                        "Relancez le recoupement pour les voir prises en compte."
                    )

        st.divider()
        st.subheader("7 · Prédiagnostic")
        st.caption(
            "Le document complet, dans la forme du prédiagnostic interne : "
            "page de garde, sommaires, zone d'étude, patrimoine naturel, zones "
            "humides, espèces par groupe et conclusion. Il reprend l'en-tête, "
            "le pied de page paginé et les styles du modèle UNITe. Ce que "
            "l'outil sait établir y est écrit — dénombrements, distances, "
            "statuts, cartes ; ce qui relève de l'expertise est laissé en "
            "couleur, avec à chaque fois la consigne de ce qu'on attend."
        )

        resultat_especes = st.session_state.get("recoupement")
        resultat_zonages = st.session_state.get("zonages")
        cartes_produites = st.session_state.get("cartes") or []

        # Ce qui manque est nommé côté **document**, pas côté outil : savoir
        # que « la section 5 est vide » n'aide pas, savoir que les volets
        # Avifaune, Chiroptères et Autre faune sortiront sans tableau, si. Et
        # c'est un avertissement, pas une légende : en petit texte gris, la
        # remarque passait inaperçue et le manque se découvrait dans Word.
        manques = []
        if resultat_zonages is None:
            manques.append("le patrimoine naturel : ni tableau de zonages ni "
                           "carte (section 4)")
        elif not cartes_produites:
            manques.append("les cartes (section 4)")
        if resultat_especes is None or not resultat_especes.especes:
            manques.append("les espèces : les volets Avifaune, Chiroptères et "
                           "Autre faune de l'état initial, ainsi que les "
                           "annexes, sortiront sans tableau (section 5)")
        if manques:
            # « Il manque encore » plutôt que « à la place de » : les éléments
            # commencent par leur article, et « à la place de les espèces »
            # ne s'élide pas.
            st.warning(
                "Il manque encore " + " ; ".join(manques) + ". Le document se "
                "produira quand même, avec une consigne en couleur à chaque "
                "emplacement : un prédiagnostic se construit par allers-"
                "retours, et refuser de produire obligerait à tout faire dans "
                "l'ordre."
            )

        col_mod, col_gen = st.columns([2, 1], gap="large")
        with col_mod:
            modele = st.file_uploader(
                "Autre modèle de mise en forme (optionnel)", type=["docx"],
                help="L'outil est livré avec son modèle : en-tête au logo, "
                     "pied de page paginé, marges et styles maison. Déposez un "
                     "document ici seulement pour en employer un autre — seuls "
                     "ses styles, son en-tête et son pied de page sont repris, "
                     "jamais son contenu.",
            )
        with col_gen:
            st.write("")
            generer = st.button("Générer le prédiagnostic", type="primary",
                                width="stretch")

        if generer:
            chemin_modele = _deposer(modele) if modele is not None else None
            citations: list[str] = []
            contexte = None

            if resultat_zonages is not None:
                _, citations_zonages = service.preparer_zonages(RACINE)
                citations += citations_zonages
            if cartes_produites:
                citations.append("Fond de carte : "
                                 + mod_cartes.FOND["attribution"])
            if resultat_especes is not None and resultat_especes.especes:
                # Les référentiels d'espèces pèsent plusieurs minutes au
                # premier chargement : on ne les demande que si le document
                # en a l'usage.
                contexte = _contexte()
                citations += list(contexte.citations)

            nom_projet = (", ".join(c.nom for c in decoupage.retenues)
                          or "la zone d'étude")
            projet = mod_prediag.Projet(
                nom=nom_projet, communes=decoupage.retenues,
                departements=departements, surface_ha=emprise.surface_ha,
                aires=_aires_etude(),
            )
            sortie = _dossier_travail() / f"Prediag_{_nom_fichier(nom_projet)}.docx"
            with st.spinner("Assemblage du document…"):
                _, recrees = mod_prediag.ecrire(
                    sortie, projet,
                    resultat_zonages=resultat_zonages,
                    cartes=cartes_produites,
                    resultat_especes=resultat_especes,
                    contexte=contexte,
                    citations=citations,
                    modele=chemin_modele,
                )
            if recrees:
                st.warning(
                    "Styles absents du modèle, recréés à l'approchant : "
                    + ", ".join(recrees)
                    + ". Déposez un document UNITe pour une mise en forme "
                    "fidèle."
                )
            st.download_button(
                "⬇️ Télécharger le prédiagnostic", sortie.read_bytes(),
                file_name=sortie.name, width="stretch",
                mime="application/vnd.openxmlformats-officedocument"
                     ".wordprocessingml.document",
            )
            st.caption(
                "Les passages en couleur du document signalent ce qui reste à "
                "compléter. À la première ouverture, Word met les sommaires à "
                "jour ; si ce n'est pas le cas, Ctrl+A puis F9. Les sources et "
                "leurs dates sont reportées en fin de document — la Licence "
                "Ouverte l'exige."
            )
