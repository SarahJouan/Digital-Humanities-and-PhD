"""Page « Import tableur » : reprise des données collectées dans un fichier Excel.

Déroulé : téléversement → choix de la feuille → association des colonnes →
simulation → application. Rien n'est écrit en base avant l'étape finale.
"""

from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

import corpus
import database
import entity_manager
import excel_import
from models import STATUTS_ANNOTATION, STATUTS_ENTITE
from ui.commun import message_erreur, titre


def afficher(cx: sqlite3.Connection) -> None:
    titre(
        "Import tableur",
        "Récupération des données déjà collectées dans un fichier Excel ou CSV : "
        "fiches d'entités et mentions annotées.",
    )

    fichier = st.file_uploader(
        "Fichier tableur (.xlsx, .xlsm, .csv, .tsv)",
        type=["xlsx", "xlsm", "xls", "csv", "tsv"],
        key="televersement_tableur",
    )
    if fichier is None:
        _aide()
        _historique(cx)
        return

    try:
        feuilles = excel_import.lire_tableur(fichier.getvalue(), fichier.name)
    except excel_import.ErreurTableur as exc:
        message_erreur(exc)
        return

    nom_feuille = st.selectbox("Feuille", list(feuilles), key="tableur_feuille")
    cadre = feuilles[nom_feuille]
    cadre = cadre.dropna(how="all")
    st.caption(f"{len(cadre)} ligne(s), {len(cadre.columns)} colonne(s).")
    st.dataframe(cadre.head(20), use_container_width=True)

    cible = st.radio(
        "Que contient cette feuille ?",
        list(excel_import.CIBLES),
        format_func=lambda c: excel_import.CIBLES[c][0],
        horizontal=True,
        key="tableur_cible",
    )

    st.divider()
    st.subheader("Association des colonnes")
    st.caption(
        "L'association est proposée automatiquement à partir des intitulés ; "
        "corrigez-la si nécessaire."
    )

    champs = excel_import.CIBLES[cible][1]
    propositions = excel_import.deviner_correspondances(cadre.columns, cible)
    colonnes_disponibles = ["— non utilisée —", *[str(c) for c in cadre.columns]]
    correspondances: dict[str, str] = {}
    grille = st.columns(2)
    for index, (champ, definition) in enumerate(champs.items()):
        with grille[index % 2]:
            defaut = propositions.get(champ, "— non utilisée —")
            if defaut not in colonnes_disponibles:
                defaut = "— non utilisée —"
            choix = st.selectbox(
                definition["libelle"] + (" *" if definition["obligatoire"] else ""),
                colonnes_disponibles,
                index=colonnes_disponibles.index(defaut),
                key=f"map_{cible}_{champ}",
            )
            if choix != "— non utilisée —":
                correspondances[champ] = choix

    manquants = [
        definition["libelle"]
        for champ, definition in champs.items()
        if definition["obligatoire"] and champ not in correspondances
    ]
    if manquants:
        st.warning("Champs obligatoires non associés : " + ", ".join(manquants))

    st.divider()
    if cible == "referentiel":
        _options_et_simulation_referentiel(
            cx, cadre, correspondances, fichier.name, bool(manquants)
        )
    else:
        _options_et_simulation_annotations(
            cx, cadre, correspondances, fichier.name, bool(manquants)
        )

    _historique(cx)


# --------------------------------------------------------------------------
def _options_et_simulation_referentiel(
    cx: sqlite3.Connection,
    cadre: pd.DataFrame,
    correspondances: dict[str, str],
    nom_fichier: str,
    bloque: bool,
) -> None:
    st.subheader("Options")
    types = entity_manager.types_entites(cx)
    colonnes = st.columns(3)
    with colonnes[0]:
        type_defaut = st.selectbox(
            "Type appliqué si la colonne est absente ou illisible",
            list(types),
            index=list(types).index("OTHER"),
            format_func=lambda c: types[c],
            key="ref_type_defaut",
        )
    with colonnes[1]:
        statuts = list(STATUTS_ENTITE)
        statut_defaut = st.selectbox(
            "Statut par défaut",
            statuts,
            index=statuts.index("a_verifier"),
            format_func=lambda s: STATUTS_ENTITE[s],
            key="ref_statut_defaut",
        )
    with colonnes[2]:
        sur_conflit = st.selectbox(
            "Si la fiche existe déjà",
            ["completer", "ignorer", "creer"],
            format_func=lambda c: {
                "completer": "Compléter la fiche existante (variantes, sources)",
                "ignorer": "Ne rien changer",
                "creer": "Créer une seconde fiche (signalée comme doublon)",
            }[c],
            key="ref_conflit",
        )

    utilisees = set(correspondances.values())
    restantes = [str(c) for c in cadre.columns if str(c) not in utilisees]
    colonnes_metadonnees = st.multiselect(
        "Colonnes à conserver comme métadonnées de la fiche",
        restantes,
        key="ref_metadonnees",
    )

    if st.button("Simuler l'import", type="primary", disabled=bloque):
        try:
            lignes = excel_import.preparer_referentiel(
                cx,
                cadre,
                correspondances,
                type_defaut,
                statut_defaut,
                sur_conflit,
                colonnes_metadonnees,
            )
            st.session_state["simulation_ref"] = lignes
        except excel_import.ErreurTableur as exc:
            message_erreur(exc)

    lignes = st.session_state.get("simulation_ref")
    if not lignes:
        return

    compte = {"creer": 0, "completer": 0, "ignorer": 0}
    for resultat in lignes:
        compte[resultat["action"]] = compte.get(resultat["action"], 0) + 1
    colonnes = st.columns(3)
    colonnes[0].metric("Fiches à créer", compte.get("creer", 0))
    colonnes[1].metric("Fiches à compléter", compte.get("completer", 0))
    colonnes[2].metric("Lignes ignorées", compte.get("ignorer", 0))

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Ligne": r["ligne"],
                    "Action": {
                        "creer": "Créer",
                        "completer": "Compléter",
                        "ignorer": "Ignorer",
                    }.get(r["action"], r["action"]),
                    "Nom": r["donnees"].get("canonical_name", ""),
                    "Type": r["donnees"].get("entity_type", ""),
                    "Variantes": "; ".join(r["donnees"].get("variants", [])),
                    "Fiche visée": r.get("cible", ""),
                    "Observations": " ".join(r["messages"]),
                }
                for r in lignes
            ]
        ),
        use_container_width=True,
        hide_index=True,
        height=320,
    )

    st.caption(
        "Aucune fusion n'est réalisée automatiquement : les rapprochements "
        "signalés doivent être vérifiés dans le référentiel."
    )
    coche = st.checkbox(
        "J'ai relu la simulation et je confirme l'import.", key="ref_confirmation"
    )
    if st.button("Importer dans le référentiel", type="primary", disabled=not coche):
        sauvegarde = database.sauvegarder(cx, etiquette="avant-import-tableur")
        rapport = excel_import.appliquer_referentiel(cx, lignes, nom_fichier)
        st.success(
            f"{rapport['creees']} fiche(s) créée(s), "
            f"{rapport['completees']} complétée(s), "
            f"{rapport['ignorees']} ignorée(s), {rapport['erreurs']} erreur(s). "
            f"Sauvegarde préalable : {sauvegarde.name}"
        )
        for detail in rapport["details"][:20]:
            st.warning(detail)
        st.session_state.pop("simulation_ref", None)


def _options_et_simulation_annotations(
    cx: sqlite3.Connection,
    cadre: pd.DataFrame,
    correspondances: dict[str, str],
    nom_fichier: str,
    bloque: bool,
) -> None:
    documents = [d for d in corpus.lister_documents(cx) if d.statut != "invalide"]
    if not documents:
        st.warning(
            "Importez d'abord les fichiers XML-TEI correspondants : les mentions "
            "doivent être rattachées à un document du corpus."
        )
        return

    st.subheader("Options")
    types = entity_manager.types_entites(cx)
    colonnes = st.columns(3)
    with colonnes[0]:
        options_documents = [None, *[d.id for d in documents]]
        document_defaut = st.selectbox(
            "Document par défaut (si la colonne est absente ou introuvable)",
            options_documents,
            format_func=lambda i: "— aucun —"
            if i is None
            else next(d.titre for d in documents if d.id == i),
            key="ann_document_defaut",
        )
    with colonnes[1]:
        type_defaut = st.selectbox(
            "Type par défaut",
            list(types),
            index=list(types).index("OTHER"),
            format_func=lambda c: types[c],
            key="ann_type_defaut",
        )
    with colonnes[2]:
        statuts = list(STATUTS_ANNOTATION)
        statut_defaut = st.selectbox(
            "Statut par défaut",
            statuts,
            index=statuts.index("a_verifier"),
            format_func=lambda s: STATUTS_ANNOTATION[s],
            key="ann_statut_defaut",
        )

    colonnes = st.columns(2)
    creer_entites = colonnes[0].checkbox(
        "Créer les fiches d'entités absentes du référentiel",
        value=True,
        key="ann_creer_entites",
    )
    toutes = colonnes[1].checkbox(
        "Annoter toutes les occurrences de chaque mention",
        value=False,
        help=(
            "Par défaut, seule la première occurrence est retenue lorsque les "
            "positions de caractères ne sont pas fournies."
        ),
        key="ann_toutes",
    )

    if st.button("Simuler l'import", type="primary", disabled=bloque):
        try:
            lignes = excel_import.preparer_annotations(
                cx,
                cadre,
                correspondances,
                document_defaut,
                type_defaut,
                statut_defaut,
                creer_entites,
                toutes,
            )
            st.session_state["simulation_ann"] = lignes
        except excel_import.ErreurTableur as exc:
            message_erreur(exc)

    lignes = st.session_state.get("simulation_ann")
    if not lignes:
        return

    a_creer = [r for r in lignes if r["action"] == "creer"]
    erreurs = [r for r in lignes if r["action"] == "erreur"]
    ignorees = [r for r in lignes if r["action"] == "ignorer"]
    nb_mentions = sum(len(r["occurrences"]) for r in a_creer)
    nb_entites = sum(1 for r in a_creer if r.get("entite_a_creer"))

    colonnes = st.columns(4)
    colonnes[0].metric("Mentions à créer", nb_mentions)
    colonnes[1].metric("Fiches à créer", nb_entites)
    colonnes[2].metric("Lignes en erreur", len(erreurs))
    colonnes[3].metric("Lignes ignorées", len(ignorees))

    titres = {d.id: d.titre for d in documents}
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Ligne": r["ligne"],
                    "Action": {
                        "creer": "Créer",
                        "erreur": "Erreur",
                        "ignorer": "Ignorer",
                    }.get(r["action"], r["action"]),
                    "Document": titres.get(r["donnees"].get("document_id"), ""),
                    "Mention": r["occurrences"][0]["surface"] if r["occurrences"] else "",
                    "Occurrences": len(r["occurrences"]),
                    "Type": r["donnees"].get("label", ""),
                    "Entité": r["donnees"].get("entity_id")
                    or (
                        r.get("entite_a_creer", {}).get("canonical_name", "")
                        if r.get("entite_a_creer")
                        else ""
                    ),
                    "Observations": " ".join(r["messages"]),
                }
                for r in lignes
            ]
        ),
        use_container_width=True,
        hide_index=True,
        height=320,
    )

    if erreurs:
        st.warning(
            f"{len(erreurs)} ligne(s) ne seront pas importées : mention absente du "
            "texte ou document introuvable."
        )

    coche = st.checkbox(
        "J'ai relu la simulation et je confirme l'import.", key="ann_confirmation"
    )
    if st.button("Importer les mentions", type="primary", disabled=not coche):
        sauvegarde = database.sauvegarder(cx, etiquette="avant-import-tableur")
        rapport = excel_import.appliquer_annotations(cx, lignes, nom_fichier)
        st.success(
            f"{rapport['creees']} mention(s) créée(s), "
            f"{rapport['completees']} mention(s) existante(s) complétée(s), "
            f"{rapport['entites_creees']} fiche(s) créée(s), "
            f"{rapport['doublons']} déjà présente(s), "
            f"{rapport['erreurs']} erreur(s). "
            f"Sauvegarde préalable : {sauvegarde.name}"
        )
        for detail in rapport["details"][:20]:
            st.warning(detail)
        st.session_state.pop("simulation_ann", None)


def _aide() -> None:
    st.info(
        "Déposez un fichier pour commencer. Les colonnes sont reconnues "
        "automatiquement à partir de leurs intitulés ; vous pouvez corriger "
        "l'association avant de lancer une simulation."
    )
    gauche, droite = st.columns(2)
    with gauche:
        st.markdown("**Feuille « référentiel » — colonnes attendues**")
        st.table(
            pd.DataFrame(
                [
                    {"Champ": definition["libelle"], "Obligatoire": "oui" if definition["obligatoire"] else "non"}
                    for definition in excel_import.CHAMPS_REFERENTIEL.values()
                ]
            )
        )
    with droite:
        st.markdown("**Feuille « annotations » — colonnes attendues**")
        st.table(
            pd.DataFrame(
                [
                    {"Champ": definition["libelle"], "Obligatoire": "oui" if definition["obligatoire"] else "non"}
                    for definition in excel_import.CHAMPS_ANNOTATIONS.values()
                ]
            )
        )
    st.caption(
        "Les variantes peuvent être séparées par des points-virgules, des barres "
        "verticales ou des retours à la ligne. Les types et statuts sont reconnus "
        "en français comme en anglais (« personne », « lieu », « validé »…)."
    )


def _historique(cx: sqlite3.Connection) -> None:
    entrees = excel_import.historique_imports(cx)
    if not entrees:
        return
    with st.expander("Historique des imports de tableurs"):
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Date": e["date"],
                        "Type": excel_import.CIBLES.get(e["type"], (e["type"],))[0],
                        "Fichier": e["fichier"],
                        "Résumé": ", ".join(
                            f"{c.replace('_', ' ')} : {v}" for c, v in e["resume"].items()
                        ),
                    }
                    for e in entrees
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
