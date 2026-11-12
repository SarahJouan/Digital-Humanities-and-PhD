"""Page « Tableau de bord »."""

from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

import annotation as annotation_module
import database
import entity_manager
import validation
from ui.commun import titre


def afficher(cx: sqlite3.Connection) -> None:
    titre(
        "Tableau de bord",
        "Vue d'ensemble du corpus, du référentiel et de l'état d'avancement.",
    )

    stats = database.statistiques(cx)

    colonnes = st.columns(4)
    colonnes[0].metric("Documents importés", stats["documents"])
    colonnes[1].metric("Entités recensées", stats["entites"])
    colonnes[2].metric("Mentions annotées", stats["annotations"])
    taux = (
        round(100 * stats["annotations_validees"] / stats["annotations"])
        if stats["annotations"]
        else 0
    )
    colonnes[3].metric("Mentions validées", stats["annotations_validees"], f"{taux} %")

    colonnes = st.columns(4)
    colonnes[0].metric("À vérifier", stats["annotations_a_verifier"])
    colonnes[1].metric("Ambiguës", stats["annotations_ambigues"])
    colonnes[2].metric("Non résolues", stats["annotations_non_resolues"])
    colonnes[3].metric("Fiches validées", stats["entites_validees"])

    if stats["documents_invalides"]:
        st.warning(
            f"{stats['documents_invalides']} fichier(s) refusé(s) à l'import. "
            "La page « Corpus » en donne le détail."
        )

    st.divider()
    gauche, droite = st.columns(2)

    with gauche:
        st.subheader("Répartition par type d'entité")
        lignes = cx.execute(
            "SELECT label, COUNT(*) AS mentions,"
            " SUM(CASE WHEN statut = 'validee' THEN 1 ELSE 0 END) AS validees"
            " FROM annotations GROUP BY label ORDER BY mentions DESC"
        ).fetchall()
        if lignes:
            types = entity_manager.types_entites(cx)
            cadre = pd.DataFrame(
                [
                    {
                        "Type": f"{types.get(l['label'], l['label'])}",
                        "Mentions": l["mentions"],
                        "Validées": l["validees"] or 0,
                    }
                    for l in lignes
                ]
            )
            st.dataframe(cadre, use_container_width=True, hide_index=True)
            st.bar_chart(cadre.set_index("Type")["Mentions"])
        else:
            st.caption("Aucune mention annotée pour le moment.")

    with droite:
        st.subheader("Entités les plus citées")
        lignes = cx.execute(
            "SELECT e.entity_id, e.canonical_name, e.entity_type,"
            " e.validation_status, COUNT(a.id) AS n"
            " FROM entites e LEFT JOIN annotations a ON a.entity_id = e.entity_id"
            " GROUP BY e.entity_id ORDER BY n DESC, e.canonical_name LIMIT 12"
        ).fetchall()
        if lignes:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Identifiant": l["entity_id"],
                            "Nom": l["canonical_name"],
                            "Type": l["entity_type"],
                            "Occurrences": l["n"],
                        }
                        for l in lignes
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("Le référentiel est vide.")

    st.divider()
    st.subheader("Entités à surveiller")
    gauche, droite = st.columns(2)

    with gauche:
        st.markdown("**Entités à variantes multiples**")
        lignes = cx.execute(
            "SELECT e.entity_id, e.canonical_name, COUNT(v.id) AS n"
            " FROM entites e JOIN variantes v ON v.entity_id = e.entity_id"
            " GROUP BY e.entity_id HAVING n > 1 ORDER BY n DESC LIMIT 10"
        ).fetchall()
        if lignes:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Identifiant": l["entity_id"],
                            "Nom": l["canonical_name"],
                            "Variantes": l["n"],
                        }
                        for l in lignes
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("Aucune entité ne présente plusieurs variantes.")

    with droite:
        st.markdown("**Mentions identifiées de façon ambiguë**")
        alertes = validation.controle_mentions_ambigues(cx)
        if alertes:
            for alerte in alertes[:10]:
                st.write(f"• {alerte.message}")
        else:
            st.caption("Aucune mention reliée à plusieurs entités.")

    st.divider()
    st.subheader("Avancement par document")
    lignes = cx.execute(
        "SELECT d.id, d.titre, d.nom_fichier, d.nb_caracteres,"
        " COUNT(a.id) AS mentions,"
        " SUM(CASE WHEN a.statut = 'validee' THEN 1 ELSE 0 END) AS validees,"
        " SUM(CASE WHEN a.entity_id IS NULL THEN 1 ELSE 0 END) AS non_resolues"
        " FROM documents d LEFT JOIN annotations a ON a.document_id = d.id"
        " WHERE d.statut <> 'invalide' GROUP BY d.id ORDER BY d.titre"
    ).fetchall()
    if lignes:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Document": l["titre"],
                        "Fichier": l["nom_fichier"],
                        "Caractères": l["nb_caracteres"],
                        "Mentions": l["mentions"],
                        "Validées": l["validees"] or 0,
                        "Non résolues": l["non_resolues"] or 0,
                    }
                    for l in lignes
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("Aucun document importé.")

    with st.expander("Dernières opérations"):
        entrees = database.lire_journal(cx, 20)
        if entrees:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Date": e["horodatage"],
                            "Action": e["action"],
                            "Détail": e["detail"],
                        }
                        for e in entrees
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("Aucune opération enregistrée.")
