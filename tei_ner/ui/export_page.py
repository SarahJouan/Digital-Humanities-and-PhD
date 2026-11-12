"""Page « Export » : référentiel JSON, corpus TEI, jeu d'entraînement JSONL."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

import pandas as pd
import streamlit as st

import corpus
import export
from ui.commun import titre

PORTEES = {
    "toutes": "Toutes les données",
    "validees": "Données validées uniquement",
    "non_validees": "Données non validées uniquement",
}


def afficher(cx: sqlite3.Connection) -> None:
    titre(
        "Export",
        "Référentiel JSON, corpus XML-TEI enrichi et jeu de données JSONL. "
        "La traçabilité entre mentions, documents et fiches est conservée.",
    )

    documents = [d for d in corpus.lister_documents(cx) if d.statut != "invalide"]
    colonnes = st.columns(3)
    with colonnes[0]:
        portee = st.selectbox(
            "Portée",
            list(PORTEES),
            format_func=lambda p: PORTEES[p],
            key="export_portee",
        )
    with colonnes[1]:
        mode_tei = st.selectbox(
            "Encodage TEI",
            ["mixte", "inline", "standoff"],
            format_func=lambda m: {
                "mixte": "Mixte (balises en ligne + standOff si nécessaire)",
                "inline": "Balises en ligne uniquement",
                "standoff": "Annotations déportées (texte intact)",
            }[m],
            key="export_mode",
        )
    with colonnes[2]:
        granularite = st.selectbox(
            "Granularité du JSONL",
            ["paragraphe", "document"],
            format_func=lambda g: {
                "paragraphe": "Un enregistrement par paragraphe (recommandé)",
                "document": "Un enregistrement par document",
            }[g],
            key="export_granularite",
        )

    selection = st.multiselect(
        "Documents (vide = tout le corpus)",
        [d.id for d in documents],
        format_func=lambda i: next(d.titre for d in documents if d.id == i),
        key="export_documents",
    )
    documents_cibles = selection or None
    horodatage = datetime.now().strftime("%Y%m%d-%H%M")

    onglets = st.tabs(
        ["Archive complète", "Référentiel JSON", "Corpus XML-TEI", "Jeu JSONL"]
    )

    with onglets[0]:
        st.markdown(
            "L'archive ZIP contient le manifeste (conventions d'offsets et date), "
            "le référentiel, le corpus réexporté, les jeux JSONL et une copie "
            "conforme des fichiers d'origine. Lorsque la portée est « toutes », "
            "les données validées et non validées sont exportées séparément."
        )
        inclure = st.checkbox("Inclure les fichiers d'origine", value=True)
        if st.button("Préparer l'archive", type="primary"):
            with st.spinner("Génération en cours…"):
                donnees = export.construire_archive(
                    cx,
                    portee=portee,
                    mode_tei=mode_tei,
                    granularite_jsonl=granularite,
                    inclure_originaux=inclure,
                    documents=documents_cibles,
                )
            st.session_state["archive"] = donnees
            st.success(f"Archive prête ({len(donnees) // 1024} Ko).")
        if st.session_state.get("archive"):
            st.download_button(
                "Télécharger l'archive ZIP",
                st.session_state["archive"],
                file_name=f"export-tei-ner-{horodatage}.zip",
                mime="application/zip",
            )

    with onglets[1]:
        donnees = export.referentiel_json(cx, portee)
        st.caption(f"{donnees['nb_entites']} fiche(s) exportée(s).")
        st.download_button(
            "Télécharger le référentiel JSON",
            json.dumps(donnees, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name=f"entites-{portee}-{horodatage}.json",
            mime="application/json",
            type="primary",
        )
        if donnees["entites"]:
            st.code(
                json.dumps(donnees["entites"][:3], ensure_ascii=False, indent=2),
                language="json",
            )

    with onglets[2]:
        if st.button("Générer le corpus TEI"):
            with st.spinner("Réécriture des documents…"):
                st.session_state["tei"] = export.documents_tei(
                    cx, portee, mode_tei, documents_cibles
                )
        resultats = st.session_state.get("tei")
        if resultats:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Fichier": r["nom_fichier"],
                            "Mentions": r.get("nb_annotations", 0),
                            "Balises en ligne": r.get("inserees_en_ligne", 0),
                            "Déportées (standOff)": r.get("reportees_standoff", 0),
                            "XML valide": "oui" if r.get("xml_valide") else "non",
                        }
                        for r in resultats
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
            reportees = [r for r in resultats if r.get("reportees_standoff")]
            if reportees:
                with st.expander("Mentions non insérées en ligne et motifs"):
                    for resultat in reportees:
                        st.markdown(f"**{resultat['nom_fichier']}**")
                        for detail in resultat["details_reportees"][:30]:
                            st.write(
                                f"• « {detail.get('surface', '')} » "
                                f"[{detail.get('debut')}, {detail.get('fin')}[ — "
                                f"{detail.get('motif')}"
                            )
            for resultat in resultats:
                if resultat.get("xml"):
                    st.download_button(
                        f"Télécharger {resultat['nom_fichier']}",
                        resultat["xml"].encode("utf-8"),
                        file_name=resultat["nom_fichier"],
                        mime="application/xml",
                        key=f"dl_tei_{resultat['document_id']}",
                    )

    with onglets[3]:
        enregistrements = export.lignes_jsonl(
            cx, portee, granularite, documents_cibles
        )
        anomalies = export.verifier_jsonl(enregistrements)
        nb_entites = sum(len(e["entities"]) for e in enregistrements)
        st.caption(
            f"{len(enregistrements)} enregistrement(s), {nb_entites} entité(s) annotée(s)."
        )
        if anomalies:
            st.error(
                f"{len(anomalies)} incohérence(s) d'offsets détectée(s). "
                "Corrigez-les depuis la page « Validation » avant d'entraîner un modèle."
            )
            st.code("\n".join(anomalies[:20]))
        else:
            st.success("Toutes les positions de caractères sont cohérentes.")
        st.download_button(
            "Télécharger le JSONL",
            export.serialiser_jsonl(enregistrements).encode("utf-8"),
            file_name=f"corpus-{portee}-{horodatage}.jsonl",
            mime="application/x-ndjson",
            type="primary",
        )
        if enregistrements:
            st.code(
                "\n".join(
                    json.dumps(e, ensure_ascii=False)[:400]
                    for e in enregistrements[:3]
                ),
                language="json",
            )
        with st.expander("Convention d'offsets utilisée"):
            st.json(export.manifeste(cx, portee)["convention_offsets"])
