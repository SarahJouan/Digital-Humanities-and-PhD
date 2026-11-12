"""Fonctions d'affichage partagées par les pages."""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable

import streamlit as st

import corpus
import entity_manager
from models import STATUTS_ANNOTATION, STATUTS_ENTITE


def titre(texte: str, aide: str = "") -> None:
    st.title(texte)
    if aide:
        st.caption(aide)


def selecteur_document(
    cx: sqlite3.Connection, cle: str, libelle: str = "Document"
) -> int | None:
    """Liste déroulante des documents valides du corpus."""
    documents = [d for d in corpus.lister_documents(cx) if d.statut != "invalide"]
    if not documents:
        st.info(
            "Aucun document dans le corpus. Rendez-vous sur la page « Corpus » "
            "pour importer des fichiers XML-TEI."
        )
        return None
    options = {d.id: f"{d.titre} — {d.nom_fichier}" for d in documents}
    identifiants = list(options)
    precedent = st.session_state.get("document_courant")
    index = identifiants.index(precedent) if precedent in identifiants else 0
    choix = st.selectbox(
        libelle,
        identifiants,
        index=index,
        format_func=lambda i: options[i],
        key=cle,
    )
    st.session_state["document_courant"] = choix
    return choix


def selecteur_type(
    cx: sqlite3.Connection, cle: str, defaut: str | None = None, libelle: str = "Type d'entité"
) -> str:
    types = entity_manager.types_entites(cx)
    codes = list(types)
    index = codes.index(defaut) if defaut in codes else 0
    return st.selectbox(
        libelle, codes, index=index, format_func=lambda c: f"{types[c]} ({c})", key=cle
    )


def selecteur_entite(
    cx: sqlite3.Connection,
    cle: str,
    entity_type: str | None = None,
    libelle: str = "Entité associée",
    autoriser_vide: bool = True,
    defaut: str | None = None,
) -> str | None:
    entites = entity_manager.lister_entites(cx, entity_type=entity_type)
    options: list[str | None] = ([None] if autoriser_vide else []) + [
        e.entity_id for e in entites
    ]
    etiquettes = {e.entity_id: f"{e.canonical_name} [{e.entity_id}]" for e in entites}
    index = options.index(defaut) if defaut in options else 0
    return st.selectbox(
        libelle,
        options,
        index=index,
        format_func=lambda i: "— aucune (mention non résolue) —" if i is None else etiquettes[i],
        key=cle,
    )


def badge_statut(statut: str, table: dict[str, str] | None = None) -> str:
    table = table or STATUTS_ANNOTATION
    couleurs = {
        "validee": "🟢",
        "a_verifier": "🟠",
        "ambigue": "🟣",
        "non_resolue": "🔴",
        "brouillon": "⚪",
        "rejetee": "⛔",
    }
    return f"{couleurs.get(statut, '•')} {table.get(statut, statut)}"


def legende_couleurs(cx: sqlite3.Connection) -> None:
    types = entity_manager.types_entites(cx)
    morceaux = [
        f'<span style="background:{corpus.couleur(code)};padding:2px 8px;'
        f'border-radius:3px;margin-right:6px;border:1px solid #bbb;">{libelle}</span>'
        for code, libelle in types.items()
    ]
    st.markdown(
        '<div style="margin:0.3rem 0 0.8rem 0;font-size:0.85rem;">'
        + "".join(morceaux)
        + "</div>",
        unsafe_allow_html=True,
    )


def confirmation(cle: str, libelle: str, bouton: str, aide: str = "") -> bool:
    """Case à cocher obligatoire avant une opération destructrice."""
    coche = st.checkbox(libelle, key=f"conf_{cle}")
    if aide:
        st.caption(aide)
    return st.button(bouton, type="primary", disabled=not coche, key=f"btn_{cle}")


def message_erreur(exception: Exception) -> None:
    st.error(f"Opération impossible : {exception}")


def tableau(donnees: Iterable[dict[str, Any]], **options: Any) -> None:
    import pandas as pd

    donnees = list(donnees)
    if not donnees:
        st.caption("Aucune donnée à afficher.")
        return
    st.dataframe(pd.DataFrame(donnees), use_container_width=True, **options)


LIBELLES_STATUT_ENTITE = STATUTS_ENTITE
LIBELLES_STATUT_ANNOTATION = STATUTS_ANNOTATION
