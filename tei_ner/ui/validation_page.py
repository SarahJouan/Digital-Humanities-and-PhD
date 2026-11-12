"""Page « Validation » : contrôles qualité et corrections proposées."""

from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

import database
import validation
from models import NIVEAUX_ALERTE
from ui.commun import titre

ICONES = {"erreur": "🔴", "avertissement": "🟠", "information": "🔵"}


def afficher(cx: sqlite3.Connection) -> None:
    titre(
        "Validation",
        "Contrôles automatiques du corpus annoté. Aucune correction n'est "
        "appliquée sans votre accord explicite.",
    )

    stats = database.statistiques(cx)
    colonnes = st.columns(5)
    colonnes[0].metric("Mentions", stats["annotations"])
    colonnes[1].metric("Validées", stats["annotations_validees"])
    colonnes[2].metric("À vérifier", stats["annotations_a_verifier"])
    colonnes[3].metric("Ambiguës", stats["annotations_ambigues"])
    colonnes[4].metric("Non résolues", stats["annotations_non_resolues"])

    st.divider()
    st.subheader("Contrôles à exécuter")
    codes = list(validation.CONTROLES)
    selection = st.multiselect(
        "Contrôles",
        codes,
        default=codes,
        format_func=lambda c: validation.CONTROLES[c][0],
        key="validation_controles",
    )

    if st.button("Lancer les contrôles", type="primary"):
        alertes = validation.executer_controles(cx, selection)
        st.session_state["alertes"] = alertes

    alertes = st.session_state.get("alertes")
    if alertes is None:
        st.info("Lancez les contrôles pour obtenir le rapport.")
        return

    compte = validation.resume(alertes)
    colonnes = st.columns(3)
    colonnes[0].metric("Erreurs", compte["erreur"])
    colonnes[1].metric("Avertissements", compte["avertissement"])
    colonnes[2].metric("Informations", compte["information"])

    if not alertes:
        st.success("Aucune anomalie détectée.")
        return

    niveaux = st.multiselect(
        "Niveaux affichés",
        list(NIVEAUX_ALERTE),
        default=["erreur", "avertissement"],
        format_func=lambda n: NIVEAUX_ALERTE[n],
        key="validation_niveaux",
    )
    visibles = [a for a in alertes if a.niveau in niveaux]

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Niveau": f"{ICONES.get(a.niveau, '')} {NIVEAUX_ALERTE[a.niveau]}",
                    "Contrôle": a.code,
                    "Message": a.message,
                    "Document": a.document_id or "",
                    "Mention": a.annotation_id or "",
                    "Entité": a.entity_id or "",
                    "Correction proposée": a.correction or "—",
                }
                for a in visibles
            ]
        ),
        use_container_width=True,
        hide_index=True,
        height=360,
    )

    st.divider()
    st.subheader("Corrections proposées")
    corrigeables = validation.corrections_possibles(visibles)
    if not corrigeables:
        st.caption("Aucune correction automatique disponible pour ces anomalies.")
        return

    st.caption(
        f"{len(corrigeables)} anomalie(s) peuvent être corrigées automatiquement. "
        "Sélectionnez celles que vous souhaitez appliquer : rien n'est modifié "
        "tant que vous n'avez pas confirmé."
    )
    par_code: dict[str, list] = {}
    for alerte in corrigeables:
        par_code.setdefault(alerte.code, []).append(alerte)

    choisies: list = []
    for code, groupe in par_code.items():
        with st.expander(
            f"{validation.CONTROLES.get(code, (code,))[0]} — {len(groupe)} cas"
        ):
            st.caption(groupe[0].correction)
            tout = st.checkbox("Tout sélectionner", key=f"corr_tout_{code}")
            etiquettes = {
                index: alerte.message for index, alerte in enumerate(groupe)
            }
            selection_groupe = st.multiselect(
                "Cas à corriger",
                list(etiquettes),
                default=list(etiquettes) if tout else [],
                format_func=lambda i, e=etiquettes: e[i][:150],
                key=f"corr_sel_{code}",
            )
            choisies.extend(groupe[i] for i in selection_groupe)

    st.write(f"**{len(choisies)} correction(s) sélectionnée(s).**")
    coche = st.checkbox(
        "Je confirme vouloir appliquer ces corrections à la base de données.",
        key="validation_confirmation",
    )
    colonnes = st.columns([1, 1, 4])
    if colonnes[0].button(
        "Sauvegarder puis corriger",
        type="primary",
        disabled=not (coche and choisies),
    ):
        chemin = database.sauvegarder(cx, etiquette="avant-corrections")
        rapport = validation.appliquer_corrections(cx, choisies)
        st.success(
            "Corrections appliquées : "
            + (", ".join(f"{v} {c.replace('_', ' ')}" for c, v in rapport.items()) or "aucune")
            + f". Sauvegarde préalable : {chemin.name}"
        )
        st.session_state["alertes"] = validation.executer_controles(cx, selection)
        st.rerun()
    if colonnes[1].button("Corriger sans sauvegarde", disabled=not (coche and choisies)):
        rapport = validation.appliquer_corrections(cx, choisies)
        st.success(
            "Corrections appliquées : "
            + (", ".join(f"{v} {c.replace('_', ' ')}" for c, v in rapport.items()) or "aucune")
        )
        st.session_state["alertes"] = validation.executer_controles(cx, selection)
        st.rerun()
