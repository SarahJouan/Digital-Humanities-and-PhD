"""Page « Annotation » : sélection d'une mention et rattachement à une entité."""

from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

import annotation as annotation_module
import corpus
import entity_manager
from models import STATUTS_ANNOTATION
from ui.commun import (
    legende_couleurs,
    message_erreur,
    selecteur_document,
    selecteur_entite,
    selecteur_type,
    titre,
)

AIDE_SELECTION = (
    "Streamlit ne permet pas de récupérer une sélection faite à la souris dans la "
    "page. La sélection se fait donc par bornes de mots (le programme calcule les "
    "positions de caractères) ou par recherche d'une chaîne dans le texte."
)


def afficher(cx: sqlite3.Connection) -> None:
    titre("Annotation", "Repérage des mentions et rattachement au référentiel.")

    document_id = selecteur_document(cx, "annotation_document")
    if document_id is None:
        return
    document = corpus.lire_document(cx, document_id)
    if document is None:
        return

    annotations = annotation_module.annotations_dict(cx, document_id)
    st.caption(
        f"{document.titre} — {document.nb_caracteres} caractères, "
        f"{len(annotations)} mention(s)."
    )

    onglets = st.tabs(
        [
            "Sélectionner dans le texte",
            "Rechercher une mention",
            "Mentions du document",
            "Créer une entité",
        ]
    )

    with onglets[0]:
        _selection_par_mots(cx, document, annotations)
    with onglets[1]:
        _selection_par_recherche(cx, document)
    with onglets[2]:
        _liste_annotations(cx, document, annotations)
    with onglets[3]:
        _creation_entite(cx)


# --------------------------------------------------------------------------
def _formulaire_rattachement(
    cx: sqlite3.Connection, prefixe: str, defaut_type: str | None = None
) -> tuple[str, str | None, str]:
    colonnes = st.columns(3)
    with colonnes[0]:
        label = selecteur_type(cx, f"{prefixe}_type", defaut_type)
    with colonnes[1]:
        entity_id = selecteur_entite(cx, f"{prefixe}_entite", entity_type=label)
    with colonnes[2]:
        statuts = list(STATUTS_ANNOTATION)
        defaut = "a_verifier" if entity_id else "non_resolue"
        statut = st.selectbox(
            "Statut",
            statuts,
            index=statuts.index(defaut),
            format_func=lambda s: STATUTS_ANNOTATION[s],
            key=f"{prefixe}_statut",
        )
    return label, entity_id, statut


def _selection_par_mots(
    cx: sqlite3.Connection, document, annotations: list[dict]
) -> None:
    st.subheader("Sélection par bornes de mots")
    st.caption(AIDE_SELECTION)

    blocs = annotation_module.paragraphes(document.texte)
    if not blocs:
        st.info("Ce document ne contient pas de texte exploitable.")
        return

    etiquettes = {
        index: f"§{index + 1} — {bloc['texte'][:70]}…" if len(bloc["texte"]) > 70
        else f"§{index + 1} — {bloc['texte']}"
        for index, bloc in enumerate(blocs)
    }
    index_bloc = st.selectbox(
        "Passage",
        list(etiquettes),
        format_func=lambda i: etiquettes[i],
        key="selection_bloc",
    )
    bloc = blocs[index_bloc]

    legende_couleurs(cx)
    st.markdown(
        corpus.texte_balise(document.texte, annotations, bloc["debut"], bloc["fin"]),
        unsafe_allow_html=True,
    )

    jetons = annotation_module.jetons(document.texte, bloc["debut"], bloc["fin"])
    if not jetons:
        st.info("Aucun mot dans ce passage.")
        return

    etiquettes_jetons = {
        index: f"{index + 1}. {jeton['texte']}" for index, jeton in enumerate(jetons)
    }
    colonnes = st.columns(2)
    with colonnes[0]:
        debut_index = st.selectbox(
            "Premier mot de la mention",
            list(etiquettes_jetons),
            format_func=lambda i: etiquettes_jetons[i],
            key="selection_debut",
        )
    with colonnes[1]:
        candidats = [i for i in etiquettes_jetons if i >= debut_index]
        fin_index = st.selectbox(
            "Dernier mot de la mention",
            candidats,
            index=0,
            format_func=lambda i: etiquettes_jetons[i],
            key="selection_fin",
        )

    debut = jetons[debut_index]["debut"]
    fin = jetons[fin_index]["fin"]
    debut, fin = annotation_module.ajuster_bornes(document.texte, debut, fin)
    surface = document.texte[debut:fin]
    st.success(f"Mention sélectionnée : « {surface} »  (positions {debut} à {fin})")

    label, entity_id, statut = _formulaire_rattachement(cx, "sel")
    note = st.text_input("Note (facultative)", key="selection_note")

    colonnes = st.columns([1, 1, 3])
    if colonnes[0].button("Enregistrer la mention", type="primary", key="selection_creer"):
        try:
            annotation_module.creer_annotation(
                cx, document.id, debut, fin, label, entity_id, statut, note=note
            )
            st.success("Mention enregistrée.")
            st.rerun()
        except annotation_module.ErreurAnnotation as exc:
            message_erreur(exc)

    if colonnes[1].button("Annoter toutes les occurrences", key="selection_toutes"):
        occurrences = annotation_module.chercher_occurrences(document.texte, surface)
        rapport = annotation_module.annoter_occurrences(
            cx, document.id, occurrences, label, entity_id, statut
        )
        st.success(
            f"{rapport['creees']} mention(s) créée(s), "
            f"{rapport.get('completees', 0)} complétée(s), "
            f"{rapport['ignorees']} déjà présente(s)."
        )
        if rapport["erreurs"]:
            st.warning(" ; ".join(rapport["erreurs"][:5]))
        st.rerun()

    if surface:
        candidats = entity_manager.chercher_correspondances(cx, surface, label)
        if candidats:
            st.caption("Entités du référentiel proches de cette mention :")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Identifiant": entite.entity_id,
                            "Nom canonique": entite.canonical_name,
                            "Score": score,
                        }
                        for entite, score in candidats
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )


def _selection_par_recherche(cx: sqlite3.Connection, document) -> None:
    st.subheader("Recherche d'une chaîne dans le texte")
    st.caption(
        "Utile pour annoter d'un seul geste toutes les occurrences d'un même nom."
    )

    colonnes = st.columns([3, 1, 1])
    chaine = colonnes[0].text_input("Mention recherchée", key="recherche_chaine")
    mots_entiers = colonnes[1].checkbox("Mots entiers", value=True, key="recherche_mots")
    sensible = colonnes[2].checkbox("Respecter la casse", value=False, key="recherche_casse")

    if not chaine.strip():
        st.info("Saisissez une chaîne à rechercher.")
        return

    occurrences = annotation_module.chercher_occurrences(
        document.texte, chaine, sensible, mots_entiers
    )
    if not occurrences:
        st.warning("Aucune occurrence trouvée dans ce document.")
        return

    st.write(f"**{len(occurrences)} occurrence(s) trouvée(s)**")
    etiquettes = {
        index: f"[{o['debut']}] …{o['gauche'][-40:]}  ⟦{o['surface']}⟧  {o['droite'][:40]}…"
        for index, o in enumerate(occurrences)
    }
    tout = st.checkbox("Tout sélectionner", value=True, key="recherche_tout")
    selection = st.multiselect(
        "Occurrences à annoter",
        list(etiquettes),
        default=list(etiquettes) if tout else [],
        format_func=lambda i: etiquettes[i],
        key="recherche_selection",
    )

    label, entity_id, statut = _formulaire_rattachement(cx, "rech")

    if st.button("Annoter la sélection", type="primary", key="recherche_creer"):
        if not selection:
            st.warning("Aucune occurrence sélectionnée.")
        else:
            rapport = annotation_module.annoter_occurrences(
                cx,
                document.id,
                [occurrences[i] for i in selection],
                label,
                entity_id,
                statut,
            )
            st.success(
                f"{rapport['creees']} mention(s) créée(s), "
                f"{rapport['ignorees']} déjà présente(s)."
            )
            if rapport["erreurs"]:
                st.warning(" ; ".join(rapport["erreurs"][:5]))
            st.rerun()


def _liste_annotations(
    cx: sqlite3.Connection, document, annotations: list[dict]
) -> None:
    st.subheader("Mentions annotées dans ce document")
    if not annotations:
        st.info("Aucune mention annotée dans ce document.")
        return

    filtre = st.columns(3)
    statut_filtre = filtre[0].selectbox(
        "Filtrer par statut",
        [None, *STATUTS_ANNOTATION],
        format_func=lambda s: "Tous" if s is None else STATUTS_ANNOTATION[s],
        key="liste_statut",
    )
    types = entity_manager.types_entites(cx)
    type_filtre = filtre[1].selectbox(
        "Filtrer par type",
        [None, *types],
        format_func=lambda t: "Tous" if t is None else types[t],
        key="liste_type",
    )
    recherche = filtre[2].text_input("Filtrer par mention", key="liste_recherche")

    visibles = [
        a
        for a in annotations
        if (statut_filtre is None or a["statut"] == statut_filtre)
        and (type_filtre is None or a["label"] == type_filtre)
        and (not recherche or recherche.lower() in a["surface"].lower())
    ]
    st.caption(f"{len(visibles)} mention(s) affichée(s).")

    noms = {
        e.entity_id: e.canonical_name for e in entity_manager.lister_entites(cx)
    }
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "N°": a["id"],
                    "Mention": a["surface"],
                    "Type": a["label"],
                    "Entité": noms.get(a["entity_id"] or "", "—"),
                    "Identifiant": a["entity_id"] or "—",
                    "Statut": STATUTS_ANNOTATION.get(a["statut"], a["statut"]),
                    "Origine": a["origine"],
                    "Début": a["debut"],
                    "Fin": a["fin"],
                }
                for a in visibles
            ]
        ),
        use_container_width=True,
        hide_index=True,
        height=320,
    )

    st.markdown("#### Modifier une mention")
    if visibles:
        options = {
            a["id"]: f"{a['id']} — « {a['surface']} » ({a['label']})" for a in visibles
        }
        cible = st.selectbox(
            "Mention",
            list(options),
            format_func=lambda i: options[i],
            key="modif_annotation",
        )
        courante = next(a for a in visibles if a["id"] == cible)
        colonnes = st.columns(3)
        with colonnes[0]:
            nouveau_type = selecteur_type(cx, "modif_type", courante["label"])
        with colonnes[1]:
            nouvelle_entite = selecteur_entite(
                cx, "modif_entite", entity_type=nouveau_type, defaut=courante["entity_id"]
            )
        with colonnes[2]:
            statuts = list(STATUTS_ANNOTATION)
            nouveau_statut = st.selectbox(
                "Statut",
                statuts,
                index=statuts.index(courante["statut"])
                if courante["statut"] in statuts
                else 0,
                format_func=lambda s: STATUTS_ANNOTATION[s],
                key="modif_statut",
            )
        note = st.text_input("Note", value=courante["note"], key="modif_note")

        boutons = st.columns([1, 1, 4])
        if boutons[0].button("Enregistrer", type="primary", key="modif_ok"):
            try:
                annotation_module.modifier_annotation(
                    cx,
                    cible,
                    label=nouveau_type,
                    entity_id=nouvelle_entite,
                    statut=nouveau_statut,
                    note=note,
                )
                st.success("Mention mise à jour.")
                st.rerun()
            except annotation_module.ErreurAnnotation as exc:
                message_erreur(exc)
        if boutons[1].button("Supprimer", key="modif_suppr"):
            st.session_state["confirmer_suppression_annotation"] = cible
        if st.session_state.get("confirmer_suppression_annotation") == cible:
            st.warning(f"Supprimer définitivement la mention {cible} ?")
            confirmation_colonnes = st.columns([1, 1, 4])
            if confirmation_colonnes[0].button("Oui, supprimer", key="modif_suppr_ok"):
                annotation_module.supprimer_annotation(cx, cible)
                st.session_state.pop("confirmer_suppression_annotation", None)
                st.success("Mention supprimée.")
                st.rerun()
            if confirmation_colonnes[1].button("Annuler", key="modif_suppr_non"):
                st.session_state.pop("confirmer_suppression_annotation", None)
                st.rerun()

    st.markdown("#### Opérations groupées")
    options = {a["id"]: f"{a['id']} — « {a['surface']} »" for a in visibles}
    lot = st.multiselect(
        "Mentions concernées",
        list(options),
        format_func=lambda i: options[i],
        key="lot_annotations",
    )
    colonnes = st.columns(3)
    with colonnes[0]:
        statuts = list(STATUTS_ANNOTATION)
        statut_lot = st.selectbox(
            "Nouveau statut",
            statuts,
            format_func=lambda s: STATUTS_ANNOTATION[s],
            key="lot_statut",
        )
        if st.button("Appliquer le statut", key="lot_statut_ok", disabled=not lot):
            annotation_module.changer_statut(cx, lot, statut_lot)
            st.success(f"{len(lot)} mention(s) mise(s) à jour.")
            st.rerun()
    with colonnes[1]:
        entite_lot = selecteur_entite(cx, "lot_entite", autoriser_vide=False)
        if st.button("Relier à cette entité", key="lot_entite_ok", disabled=not lot):
            try:
                annotation_module.relier_entite(cx, lot, entite_lot)
                st.success(f"{len(lot)} mention(s) reliée(s).")
                st.rerun()
            except annotation_module.ErreurAnnotation as exc:
                message_erreur(exc)
    with colonnes[2]:
        st.write("")
        if st.button("Supprimer la sélection", key="lot_suppr", disabled=not lot):
            st.session_state["confirmer_lot"] = list(lot)
        if st.session_state.get("confirmer_lot"):
            st.warning(
                f"Supprimer définitivement {len(st.session_state['confirmer_lot'])} "
                "mention(s) ?"
            )
            if st.button("Oui, supprimer", key="lot_suppr_ok"):
                annotation_module.supprimer_annotations(
                    cx, st.session_state.pop("confirmer_lot")
                )
                st.success("Mentions supprimées.")
                st.rerun()
            if st.button("Annuler", key="lot_suppr_non"):
                st.session_state.pop("confirmer_lot", None)
                st.rerun()


def _creation_entite(cx: sqlite3.Connection) -> None:
    st.subheader("Créer une entité sans quitter l'annotation")
    with st.form("creation_entite_rapide"):
        colonnes = st.columns(2)
        with colonnes[0]:
            types = entity_manager.types_entites(cx)
            entity_type = st.selectbox(
                "Type", list(types), format_func=lambda c: f"{types[c]} ({c})"
            )
            nom = st.text_input("Nom canonique")
        with colonnes[1]:
            variantes = st.text_area(
                "Variantes (une par ligne)", height=100, placeholder="Delacroix\nM. Delacroix"
            )
            description = st.text_input("Description")
        envoye = st.form_submit_button("Créer la fiche", type="primary")
    if envoye:
        try:
            entite = entity_manager.creer_entite(
                cx,
                entity_type=entity_type,
                canonical_name=nom,
                description=description,
                variants=[v.strip() for v in variantes.splitlines() if v.strip()],
                validation_status="a_verifier",
            )
            st.success(
                f"Fiche {entite.entity_id} créée. Elle est disponible dans les "
                "listes déroulantes ci-dessus."
            )
            doublons = [
                d
                for d in entity_manager.detecter_doublons(cx)
                if entite.entity_id in (d["a"].entity_id, d["b"].entity_id)
            ]
            for doublon in doublons:
                st.warning(
                    f"Doublon possible avec {doublon['b'].entity_id} "
                    f"(« {doublon['b'].canonical_name} ») : {doublon['motif']}. "
                    "Aucune fusion n'est effectuée automatiquement."
                )
        except entity_manager.ErreurEntite as exc:
            message_erreur(exc)
