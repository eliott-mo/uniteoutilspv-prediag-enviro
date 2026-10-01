"""Pré-diagnostic environnemental — tenue à jour des statuts et pré-remplissage.

Deux onglets, dans l'ordre où on s'en sert :

    A · Mise à jour des tables  — ce qui a bougé dans les référentiels depuis
                                  la dernière révision des classeurs B-Statuts
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
from prediag_enviro import service, veille  # noqa: E402
from prediag_enviro import sortie_word as mod_word  # noqa: E402
from prediag_enviro.memoire import ACCEPTE, A_REVOIR, DECISIONS, REFUSE  # noqa: E402

#: Le picto de l'outil, devant son titre et dans l'onglet du navigateur : les
#: outils UNITe portent tous le leur, et le chef de projet qui en ouvre
#: plusieurs les distingue dans sa barre d'onglets avant d'avoir lu un mot.
PICTO = "🦉"

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
        "d'espèces · Tableaux Word aux conventions UNITe"
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


@st.cache_resource(show_spinner="Lecture des classeurs B-Statuts…")
def _classeurs(_jeton: float):
    """`_jeton` force la relecture quand un classeur est redéposé."""
    return service.charger_classeurs(RACINE)


def _jeton_classeurs() -> float:
    """Empreinte de fraîcheur du dossier classeurs/."""
    dossier = RACINE / "classeurs"
    return max((p.stat().st_mtime for p in dossier.glob("*.xlsx")), default=0.0)


def _memoire():
    if "memoire" not in st.session_state:
        st.session_state.memoire = service.memoire_projet(RACINE)
    return st.session_state.memoire


def _dossier_travail() -> Path:
    """Dossier temporaire du dépôt courant, conservé le temps de la session."""
    if "dossier_travail" not in st.session_state:
        st.session_state.dossier_travail = Path(tempfile.mkdtemp(prefix="prediag_"))
    return st.session_state.dossier_travail


def _deposer(fichier) -> Path:
    cible = _dossier_travail() / fichier.name
    cible.write_bytes(fichier.getbuffer())
    return cible


onglet_a, onglet_b = st.tabs([
    "A · Mise à jour des tables",
    "B · Prédiag",
])


# ══════════════════════════════════════════════════════════════════════════════
#  VOLET A — Mise à jour des tables
# ══════════════════════════════════════════════════════════════════════════════
with onglet_a:
    st.subheader("1 · État du référentiel")

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
        if st.button("Rafraîchir les référentiels", help="Retélécharge TaxRef et "
                     "BDC-Statuts depuis l'INPN, puis reconstruit les index."):
            service.charger_contexte(RACINE, forcer=True)
            _contexte.clear()
            st.rerun()

    with col_classeurs:
        if not cs:
            st.warning(
                f"Aucun classeur dans `classeurs/`. Y déposer les fichiers "
                f"B-Statuts (noms reconnus : {', '.join(service.MOTIFS.values())})."
            )
        else:
            st.dataframe(
                pd.DataFrame([{
                    "Groupe": groupe,
                    "Taxons": len(cl.taxons),
                    "Colonnes": len(cl.colonnes),
                    "Comparables": sum(1 for c in cl.colonnes if c.comparable),
                } for groupe, cl in cs.items()]),
                hide_index=True, width="stretch",
            )

    if cs:
        st.divider()
        st.subheader("2 · Vérifier ce qui a bougé")

        col_g, col_t, col_b = st.columns([2, 2, 1], gap="large")
        with col_g:
            groupes = st.multiselect("Groupes", list(cs), default=list(cs))
        with col_t:
            territoires = st.text_input(
                "Territoires", placeholder="Normandie, Grand Est…",
                help="Laisser vide pour tout passer. Les statuts nationaux et "
                     "européens remontent de toute façon.",
            )
        with col_b:
            st.write("")
            lancer = st.button("Vérifier", type="primary", width="stretch")

        if lancer:
            with st.spinner("Comparaison aux référentiels…"):
                res, masques = service.lancer_veille(
                    ctx, cs, memoire, groupes=groupes or None,
                    territoires=[t.strip() for t in territoires.split(",") if t.strip()] or None,
                )
            st.session_state.veille = res
            st.session_state.veille_masques = masques

        res = st.session_state.get("veille")
        if res is not None:
            masques = st.session_state.get("veille_masques", 0)
            st.divider()
            st.subheader("3 · Arbitrer")

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


# ══════════════════════════════════════════════════════════════════════════════
#  VOLET B — Prédiag
# ══════════════════════════════════════════════════════════════════════════════
with onglet_b:
    st.subheader("1 · Périmètre du projet")
    st.caption(
        "Archive ZIP d'un shapefile complet (`.shp`, `.shx`, `.dbf`, `.prj`), "
        "ou fichier KML / GeoJSON."
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

        if "decoupage" not in st.session_state:
            with st.spinner("Intersection avec les contours communaux…"):
                st.session_state.decoupage = mod_communes.communes_concernees(
                    emprise, cache=RACINE / "referentiels"
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
            "Rayons par défaut d'après le guide du ministère (2016), à ajuster "
            "selon le projet."
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
        st.subheader("4 · Sources d'espèces")
        st.caption(
            "Déposez ce que vous avez trouvé : exports Excel ou CSV, PDF, "
            "captures d'écran. Un export avec les noms latins vaut dix captures "
            "— 98,6 % d'appariement contre 81 %."
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
            st.subheader("5 · Liste recoupée")

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
            st.subheader("6 · Tableau Word")

            col_mod, col_gen = st.columns([2, 1], gap="large")
            with col_mod:
                modele = st.file_uploader(
                    "Modèle de mise en forme (optionnel)", type=["docx"],
                    help="N'importe quel document UNITe : seuls ses styles sont "
                         "repris (« Titre colonne », « Corps de texte - Unite »). "
                         "Sans modèle, les styles sont recréés à l'approchant.",
                )
            with col_gen:
                st.write("")
                generer = st.button("Générer le document", type="primary",
                                    width="stretch", disabled=not resultat.especes)

            if generer:
                chemin_modele = _deposer(modele) if modele is not None else None
                colonnes = mod_word.colonnes_especes([])
                par_groupe: dict[str, list[dict]] = {}
                for espece in resultat.especes:
                    par_groupe.setdefault(espece.groupe, []).append({
                        "nom_commun": espece.nom_commun,
                        "nom_scientifique": espece.nom_scientifique,
                        "nidification": espece.nidification,
                        "date_obs": espece.date_obs,
                    })
                communes_libelle = (", ".join(c.nom for c in decoupage.retenues)
                                    or "la zone d'étude")
                blocs = [
                    (groupe.capitalize(), colonnes, lignes,
                     f"Tableau : espèces de {groupe} recensées sur "
                     f"{communes_libelle}")
                    for groupe, lignes in par_groupe.items()
                ]
                sortie = _dossier_travail() / "tableaux_especes.docx"
                _, recrees = mod_word.ecrire_document(
                    sortie, f"État initial — {communes_libelle}", blocs,
                    modele=chemin_modele,
                    mentions=[
                        "Sources : " + ", ".join(sorted({
                            s for e in resultat.especes for s in e.sources})),
                        "Statuts et taxonomie : " + " · ".join(_contexte().citations),
                    ],
                )
                if recrees:
                    st.warning(
                        "Styles absents du modèle, recréés à l'approchant : "
                        + ", ".join(recrees)
                    )
                st.download_button(
                    "⬇️ Télécharger les tableaux", sortie.read_bytes(),
                    file_name=sortie.name, width="stretch",
                    mime="application/vnd.openxmlformats-officedocument"
                         ".wordprocessingml.document",
                )
                st.caption(
                    "Tableaux aux conventions UNITe : en-têtes « Titre colonne », "
                    "corps « Corps de texte - Unite », noms latins en italique, "
                    "dates centrées. Plus de copier-coller ni de remise en forme."
                )
