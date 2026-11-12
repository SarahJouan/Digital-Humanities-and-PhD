"""Page « Corpus » : import et consultation des documents XML-TEI."""

from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

import annotation as annotation_module
import corpus
from ui.commun import confirmation, legende_couleurs, titre


def afficher(cx: sqlite3.Connection) -> None:
    titre(
        "Corpus",
        "Import des fichiers XML-TEI, consultation du texte et des métadonnées. "
        "Les fichiers d'origine ne sont jamais modifiés.",
    )

    onglet_import, onglet_liste, onglet_lecture = st.tabs(
        ["Importer", "Documents importés", "Lire un document"]
    )

    # ----------------------------------------------------------------- import
    with onglet_import:
        st.subheader("Importer des fichiers XML-TEI")
        fichiers = st.file_uploader(
            "Fichiers XML-TEI (.xml)",
            type=["xml", "tei"],
            accept_multiple_files=True,
            key="televersement_tei",
        )
        reprendre = st.checkbox(
            "Reprendre les entités déjà encodées dans le XML "
            "(persName, placeName, orgName, title, rs…)",
            value=True,
            help=(
                "Les mentions détectées sont créées avec le statut « non résolue » : "
                "elles devront être reliées à une fiche du référentiel."
            ),
        )
        if fichiers and st.button("Lancer l'import", type="primary"):
            resultats = []
            barre = st.progress(0.0)
            for index, fichier in enumerate(fichiers, start=1):
                compte_rendu = corpus.importer_fichier(
                    cx, fichier.getvalue(), fichier.name, reprendre
                )
                resultats.append(compte_rendu)
                barre.progress(index / len(fichiers))
            barre.empty()
            for compte_rendu in resultats:
                if compte_rendu["statut"] == "importe":
                    st.success(f"{compte_rendu['fichier']} — {compte_rendu['message']}")
                elif compte_rendu["statut"] == "doublon":
                    st.info(f"{compte_rendu['fichier']} — {compte_rendu['message']}")
                else:
                    st.error(f"{compte_rendu['fichier']} — {compte_rendu['message']}")
            st.caption("Import terminé. Les données sont enregistrées.")

        st.divider()
        st.markdown(
            "**Ce qui est conservé :** le XML d'origine intégral, l'identifiant "
            "`xml:id` du document, le `teiHeader` complet et les principales "
            "métadonnées (titre, auteur, éditeur, date, source, langue)."
        )

    # ------------------------------------------------------------------ liste
    with onglet_liste:
        documents = corpus.lister_documents(cx)
        if not documents:
            st.info("Aucun document importé.")
        else:
            comptes = {
                ligne["document_id"]: ligne["n"]
                for ligne in cx.execute(
                    "SELECT document_id, COUNT(*) AS n FROM annotations"
                    " GROUP BY document_id"
                )
            }
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "N°": d.id,
                            "Titre": d.titre,
                            "Fichier": d.nom_fichier,
                            "xml:id": d.tei_id or "",
                            "Caractères": d.nb_caracteres,
                            "Mentions": comptes.get(d.id, 0),
                            "Statut": d.statut,
                            "Importé le": d.cree_le,
                        }
                        for d in documents
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )
            invalides = [d for d in documents if d.statut == "invalide"]
            if invalides:
                st.subheader("Fichiers refusés")
                for document in invalides:
                    st.error(f"**{document.nom_fichier}** — {document.message_erreur}")

            st.subheader("Supprimer un document")
            options = {d.id: f"{d.titre} — {d.nom_fichier}" for d in documents}
            cible = st.selectbox(
                "Document à supprimer",
                list(options),
                format_func=lambda i: options[i],
                key="suppression_document",
            )
            nb = comptes.get(cible, 0)
            if confirmation(
                "suppr_doc",
                f"Je confirme la suppression du document et de ses {nb} annotation(s).",
                "Supprimer définitivement",
                "Le fichier d'origine sur votre disque n'est pas touché.",
            ):
                corpus.supprimer_document(cx, cible)
                st.success("Document supprimé.")
                st.rerun()

    # ---------------------------------------------------------------- lecture
    with onglet_lecture:
        documents = [d for d in corpus.lister_documents(cx) if d.statut != "invalide"]
        if not documents:
            st.info("Aucun document consultable.")
            return
        options = {d.id: f"{d.titre} — {d.nom_fichier}" for d in documents}
        identifiants = list(options)
        precedent = st.session_state.get("document_courant")
        index = identifiants.index(precedent) if precedent in identifiants else 0
        choix = st.selectbox(
            "Document",
            identifiants,
            index=index,
            format_func=lambda i: options[i],
            key="lecture_document",
        )
        st.session_state["document_courant"] = choix

        navigation = st.columns([1, 1, 6])
        if navigation[0].button("◀ Précédent", disabled=index == 0):
            st.session_state["document_courant"] = identifiants[max(0, index - 1)]
            st.rerun()
        if navigation[1].button("Suivant ▶", disabled=index >= len(identifiants) - 1):
            st.session_state["document_courant"] = identifiants[
                min(len(identifiants) - 1, index + 1)
            ]
            st.rerun()

        document = corpus.lire_document(cx, choix)
        if document is None:
            return

        with st.expander("Métadonnées TEI", expanded=False):
            metadonnees = {
                cle: valeur
                for cle, valeur in document.metadonnees.items()
                if cle != "teiHeader_xml"
            }
            if metadonnees:
                st.table(
                    pd.DataFrame(
                        [{"Champ": c, "Valeur": v} for c, v in metadonnees.items()]
                    ).set_index("Champ")
                )
            else:
                st.caption("Aucune métadonnée extraite du teiHeader.")
            if "teiHeader_xml" in document.metadonnees:
                st.code(document.metadonnees["teiHeader_xml"][:4000], language="xml")

        annotations = annotation_module.annotations_dict(cx, document.id)
        st.caption(
            f"{document.nb_caracteres} caractères · {len(annotations)} mention(s) annotée(s)"
        )
        surligner = st.checkbox("Surligner les mentions annotées", value=True)
        legende_couleurs(cx)

        blocs = annotation_module.paragraphes(document.texte)
        par_page = 25
        pages = max(1, (len(blocs) + par_page - 1) // par_page)
        page = (
            st.number_input(
                "Page", min_value=1, max_value=pages, value=1, step=1, key="page_lecture"
            )
            if pages > 1
            else 1
        )
        selection = blocs[(page - 1) * par_page : page * par_page]
        if selection:
            debut = selection[0]["debut"]
            fin = selection[-1]["fin"]
            if surligner:
                st.markdown(
                    corpus.texte_balise(document.texte, annotations, debut, fin),
                    unsafe_allow_html=True,
                )
            else:
                st.text_area(
                    "Texte",
                    document.texte[debut:fin],
                    height=420,
                    label_visibility="collapsed",
                )
            st.caption(f"Positions {debut} à {fin} — page {page} sur {pages}")

        with st.expander("XML source (lecture seule)"):
            st.code(document.xml_source[:20000], language="xml")
            st.download_button(
                "Télécharger une copie du fichier d'origine",
                document.xml_source.encode("utf-8"),
                file_name=document.nom_fichier,
                mime="application/xml",
            )
