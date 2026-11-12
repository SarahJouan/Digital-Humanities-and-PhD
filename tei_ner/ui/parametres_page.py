"""Page « Paramètres » : types d'entités, sauvegardes, conventions, maintenance."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

import database
import entity_manager
from models import TYPES_ENTITES_DEFAUT, UNICODE_NORMALISATION
from ui.commun import confirmation, message_erreur, titre


def afficher(cx: sqlite3.Connection) -> None:
    titre("Paramètres", "Configuration, sauvegardes et informations techniques.")

    onglets = st.tabs(
        ["Types d'entités", "Sauvegarde et restauration", "Base de données", "Conventions"]
    )

    with onglets[0]:
        _types(cx)
    with onglets[1]:
        _sauvegardes(cx)
    with onglets[2]:
        _base(cx)
    with onglets[3]:
        _conventions()


def _types(cx: sqlite3.Connection) -> None:
    types = entity_manager.types_entites(cx)
    st.subheader("Types d'entités disponibles")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Code": code,
                    "Libellé": libelle,
                    "Origine": "initial" if code in TYPES_ENTITES_DEFAUT else "ajouté",
                }
                for code, libelle in types.items()
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        "Les six types initiaux ne peuvent pas être supprimés. Les types ajoutés "
        "sont exportés en TEI sous la forme <rs type=\"…\">."
    )
    with st.form("ajout_type"):
        colonnes = st.columns(2)
        code = colonnes[0].text_input("Code (majuscules)", placeholder="ARTWORK")
        libelle = colonnes[1].text_input("Libellé affiché", placeholder="Œuvre d'art")
        if st.form_submit_button("Ajouter ce type"):
            try:
                entity_manager.ajouter_type(cx, code, libelle)
                st.success(f"Type « {libelle} » ajouté.")
                st.rerun()
            except entity_manager.ErreurEntite as exc:
                message_erreur(exc)


def _sauvegardes(cx: sqlite3.Connection) -> None:
    st.subheader("Créer une sauvegarde")
    st.caption(
        f"Les sauvegardes sont déposées dans `{database.DOSSIER_SAUVEGARDES}`. "
        "Une sauvegarde est également créée automatiquement avant toute "
        "correction en lot et avant tout import de tableur."
    )
    etiquette = st.text_input("Étiquette (facultative)", placeholder="avant-relecture")
    if st.button("Sauvegarder maintenant", type="primary"):
        chemin = database.sauvegarder(cx, etiquette=etiquette.strip())
        st.success(f"Sauvegarde créée : {chemin}")
        st.rerun()

    st.divider()
    st.subheader("Sauvegardes disponibles")
    sauvegardes = database.lister_sauvegardes()
    if not sauvegardes:
        st.caption("Aucune sauvegarde pour le moment.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Fichier": chemin.name,
                        "Taille (Ko)": round(chemin.stat().st_size / 1024, 1),
                        "Date": pd.Timestamp(chemin.stat().st_mtime, unit="s").strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                    }
                    for chemin in sauvegardes
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
        for chemin in sauvegardes[:5]:
            st.download_button(
                f"Télécharger {chemin.name}",
                chemin.read_bytes(),
                file_name=chemin.name,
                mime="application/octet-stream",
                key=f"dl_bk_{chemin.name}",
            )

    st.divider()
    st.subheader("Restaurer une sauvegarde")
    st.warning(
        "La restauration remplace l'intégralité de la base courante. Une copie "
        "de sécurité de l'état actuel est créée automatiquement. "
        "**Après restauration, arrêtez puis relancez l'application** "
        "(Ctrl+C dans le terminal, puis `streamlit run app.py`)."
    )
    if sauvegardes:
        choix = st.selectbox(
            "Sauvegarde à restaurer",
            sauvegardes,
            format_func=lambda c: c.name,
            key="restauration_choix",
        )
        if confirmation(
            "restaurer",
            "Je confirme le remplacement de la base de données courante.",
            "Restaurer cette sauvegarde",
        ):
            try:
                cx.close()
                st.cache_resource.clear()
                cible = database.restaurer(choix)
                st.success(
                    f"Base restaurée depuis {choix.name} vers {cible}. "
                    "Relancez l'application pour reprendre le travail."
                )
                st.stop()
            except database.ErreurBase as exc:
                message_erreur(exc)


def _base(cx: sqlite3.Connection) -> None:
    chemin = Path(st.session_state.get("chemin_base", str(database.CHEMIN_BASE_DEFAUT)))
    st.subheader("Informations")
    taille = chemin.stat().st_size / 1024 if chemin.exists() else 0
    st.table(
        pd.DataFrame(
            [
                {"Paramètre": "Fichier", "Valeur": str(chemin)},
                {"Paramètre": "Taille", "Valeur": f"{taille:.1f} Ko"},
                {
                    "Paramètre": "Version du schéma",
                    "Valeur": database.lire_parametre(cx, "schema_version", "?"),
                },
                {
                    "Paramètre": "Créée le",
                    "Valeur": database.lire_parametre(cx, "creee_le", "?"),
                },
                {"Paramètre": "Dossier des exports", "Valeur": str(database.DOSSIER_EXPORTS)},
            ]
        ).set_index("Paramètre")
    )
    st.caption(
        "Aucune donnée du corpus n'est transmise à un service externe : "
        "l'application fonctionne entièrement en local."
    )

    st.divider()
    st.subheader("Réinitialiser les données de travail")
    st.error(
        "Cette opération efface documents, entités et annotations. "
        "Le schéma et les paramètres sont conservés."
    )
    if confirmation(
        "reinit",
        "Je confirme l'effacement de toutes les données de travail.",
        "Effacer toutes les données",
        "Une sauvegarde est créée juste avant l'effacement.",
    ):
        chemin_sauvegarde = database.sauvegarder(cx, etiquette="avant-reinitialisation")
        database.reinitialiser(cx)
        st.success(f"Données effacées. Sauvegarde : {chemin_sauvegarde.name}")
        st.rerun()


def _conventions() -> None:
    st.subheader("Positions de caractères")
    st.markdown(
        f"""
Les positions enregistrées dans la base et exportées en JSONL sont des
**indices de points de code Unicode** dans le texte brut du document, après
normalisation **{UNICODE_NORMALISATION}**. Les intervalles sont semi-ouverts :
`[début, fin[`, de sorte que `fin − début` est le nombre de caractères.

Le texte brut de référence est obtenu ainsi :

1. parcours en ordre documentaire de l'élément `<text>` du fichier TEI
   (le `teiHeader`, le `facsimile` et le `standOff` sont exclus) ;
2. réduction de toute suite d'espaces, tabulations et retours à la ligne
   à une espace simple ;
3. insertion d'un saut de ligne entre les éléments de bloc
   (`p`, `div`, `head`, `lg`, `l`, `item`, `note`…).

Chaque fragment de texte conserve un lien vers le nœud XML dont il provient :
c'est ce qui permet de réinjecter les balises exactement au bon endroit lors
de l'export, sans jamais modifier le fichier d'origine.
"""
    )
    st.subheader("Encodage TEI des entités")
    st.table(
        pd.DataFrame(
            [
                {"Type": "PERSON", "Balise": "<persName ref=\"#ID\">"},
                {"Type": "PLACE", "Balise": "<placeName ref=\"#ID\">"},
                {"Type": "ORG", "Balise": "<orgName ref=\"#ID\">"},
                {"Type": "WORK", "Balise": "<title ref=\"#ID\">"},
                {"Type": "EVENT", "Balise": "<rs type=\"event\" ref=\"#ID\">"},
                {"Type": "OTHER et types ajoutés", "Balise": "<rs type=\"…\" ref=\"#ID\">"},
            ]
        ).set_index("Type")
    )
    st.markdown(
        """
Les fiches d'entités sont déclarées dans `<standOff>` (`<listPerson>`,
`<listPlace>`, `<listOrg>`, `<list type="…">`), ce qui rend les renvois
`@ref` résolubles à l'intérieur du fichier exporté.

Lorsqu'une mention ne peut pas être balisée en ligne — parce qu'elle
chevauche une autre annotation ou qu'elle traverse plusieurs éléments XML —
elle est déportée dans `<standOff><listAnnotation>` sous forme de `<span>`
dont l'attribut `@target` suit le schéma de pointeur `char=début,fin`.
Le mode « annotations déportées » applique ce traitement à toutes les
mentions et laisse le texte rigoureusement intact.

Les choix d'encodage sont consignés dans `<encodingDesc><appInfo>` du
fichier exporté.
"""
    )
