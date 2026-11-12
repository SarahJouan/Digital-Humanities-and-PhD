"""Page « Référentiel des entités »."""

from __future__ import annotations

import json
import sqlite3

import pandas as pd
import streamlit as st

import annotation as annotation_module
import entity_manager
from models import CHAMPS_METADONNEES, STATUTS_ENTITE
from ui.commun import message_erreur, titre


def afficher(cx: sqlite3.Connection) -> None:
    titre(
        "Référentiel des entités",
        "Fiches d'autorité : identifiant stable, nom canonique, variantes, "
        "description, métadonnées, sources et statut de validation.",
    )

    onglets = st.tabs(
        ["Consulter et modifier", "Créer une fiche", "Doublons potentiels"]
    )
    with onglets[0]:
        _consulter(cx)
    with onglets[1]:
        _creer(cx)
    with onglets[2]:
        _doublons(cx)


def _consulter(cx: sqlite3.Connection) -> None:
    types = entity_manager.types_entites(cx)
    colonnes = st.columns([3, 1, 1])
    recherche = colonnes[0].text_input(
        "Recherche (nom, variante, identifiant, description)", key="ref_recherche"
    )
    type_filtre = colonnes[1].selectbox(
        "Type",
        [None, *types],
        format_func=lambda t: "Tous" if t is None else types[t],
        key="ref_type",
    )
    statut_filtre = colonnes[2].selectbox(
        "Statut",
        [None, *STATUTS_ENTITE],
        format_func=lambda s: "Tous" if s is None else STATUTS_ENTITE[s],
        key="ref_statut",
    )

    entites = entity_manager.lister_entites(cx, recherche, type_filtre, statut_filtre)
    st.caption(f"{len(entites)} fiche(s).")
    if not entites:
        st.info("Aucune fiche ne correspond à ces critères.")
        return

    comptes = {
        ligne["entity_id"]: ligne["n"]
        for ligne in cx.execute(
            "SELECT entity_id, COUNT(*) AS n FROM annotations"
            " WHERE entity_id IS NOT NULL GROUP BY entity_id"
        )
    }
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Identifiant": e.entity_id,
                    "Type": types.get(e.entity_type, e.entity_type),
                    "Nom canonique": e.canonical_name,
                    "Variantes": len(e.variants),
                    "Occurrences": comptes.get(e.entity_id, 0),
                    "Statut": STATUTS_ENTITE.get(e.validation_status, e.validation_status),
                    "Modifiée le": e.updated_at,
                }
                for e in entites
            ]
        ),
        use_container_width=True,
        hide_index=True,
        height=300,
    )

    st.divider()
    options = {e.entity_id: f"{e.canonical_name} [{e.entity_id}]" for e in entites}
    cible = st.selectbox(
        "Fiche à consulter ou modifier",
        list(options),
        format_func=lambda i: options[i],
        key="ref_fiche",
    )
    entite = entity_manager.lire_entite(cx, cible)
    if entite is None:
        return

    gauche, droite = st.columns([3, 2])

    with gauche:
        with st.form(f"fiche_{cible}"):
            st.markdown(f"#### Fiche `{entite.entity_id}`")
            colonnes = st.columns(2)
            with colonnes[0]:
                codes = list(types)
                nouveau_type = st.selectbox(
                    "Type d'entité",
                    codes,
                    index=codes.index(entite.entity_type)
                    if entite.entity_type in codes
                    else 0,
                    format_func=lambda c: f"{types[c]} ({c})",
                )
                nom = st.text_input("Nom canonique", value=entite.canonical_name)
            with colonnes[1]:
                statuts = list(STATUTS_ENTITE)
                statut = st.selectbox(
                    "Statut de validation",
                    statuts,
                    index=statuts.index(entite.validation_status)
                    if entite.validation_status in statuts
                    else 0,
                    format_func=lambda s: STATUTS_ENTITE[s],
                )
                note = st.text_input("Note de travail", value=entite.note)
            description = st.text_area("Description", value=entite.description, height=80)
            variantes = st.text_area(
                "Variantes orthographiques et historiques (une par ligne)",
                value="\n".join(entite.variants),
                height=110,
            )
            sources = st.text_area(
                "Sources documentaires (une par ligne)",
                value="\n".join(entite.sources),
                height=80,
            )

            st.markdown("**Métadonnées spécifiques au type**")
            metadonnees = dict(entite.metadata)
            champs = CHAMPS_METADONNEES.get(nouveau_type, CHAMPS_METADONNEES["OTHER"])
            colonnes = st.columns(2)
            for index, (clef, libelle) in enumerate(champs):
                with colonnes[index % 2]:
                    metadonnees[clef] = st.text_input(
                        libelle, value=str(metadonnees.get(clef, "")), key=f"meta_{cible}_{clef}"
                    )
            supplementaires = st.text_area(
                "Autres métadonnées (JSON)",
                value=json.dumps(
                    {
                        c: v
                        for c, v in entite.metadata.items()
                        if c not in {clef for clef, _ in champs}
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                if any(c not in {clef for clef, _ in champs} for c in entite.metadata)
                else "{}",
                height=80,
            )
            enregistrer = st.form_submit_button("Enregistrer la fiche", type="primary")

        if enregistrer:
            try:
                supplement = json.loads(supplementaires or "{}")
            except json.JSONDecodeError as exc:
                st.error(f"Le champ « Autres métadonnées » n'est pas un JSON valide : {exc}")
                supplement = None
            if supplement is not None:
                metadonnees = {
                    c: v for c, v in {**supplement, **metadonnees}.items() if str(v).strip()
                }
                try:
                    entity_manager.modifier_entite(
                        cx,
                        cible,
                        entity_type=nouveau_type,
                        canonical_name=nom,
                        description=description,
                        variants=[v.strip() for v in variantes.splitlines() if v.strip()],
                        sources=[s.strip() for s in sources.splitlines() if s.strip()],
                        metadata=metadonnees,
                        validation_status=statut,
                        note=note,
                    )
                    st.success("Fiche enregistrée.")
                    st.rerun()
                except entity_manager.ErreurEntite as exc:
                    message_erreur(exc)

        st.markdown("##### Supprimer la fiche")
        nb = comptes.get(cible, 0)
        if st.button("Supprimer cette fiche", key=f"suppr_{cible}"):
            st.session_state["confirmer_suppression_entite"] = cible
        if st.session_state.get("confirmer_suppression_entite") == cible:
            st.warning(
                f"La fiche {cible} sera supprimée. Les {nb} mention(s) liée(s) "
                "deviendront « non résolues » (elles ne sont pas supprimées)."
            )
            colonnes = st.columns([1, 1, 4])
            if colonnes[0].button("Oui, supprimer", key=f"suppr_ok_{cible}"):
                entity_manager.supprimer_entite(cx, cible)
                st.session_state.pop("confirmer_suppression_entite", None)
                st.success("Fiche supprimée.")
                st.rerun()
            if colonnes[1].button("Annuler", key=f"suppr_non_{cible}"):
                st.session_state.pop("confirmer_suppression_entite", None)
                st.rerun()

    with droite:
        st.markdown("#### Occurrences dans le corpus")
        occurrences = annotation_module.occurrences_entite(cx, cible)
        st.caption(f"{len(occurrences)} occurrence(s).")
        if occurrences:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Document": o["document"],
                            "Mention": o["surface"],
                            "Position": o["debut"],
                            "Statut": o["statut"],
                        }
                        for o in occurrences
                    ]
                ),
                use_container_width=True,
                hide_index=True,
                height=220,
            )
            with st.expander("Contextes"):
                for occurrence in occurrences[:50]:
                    st.write(f"**{occurrence['document']}** — {occurrence['contexte']}")
        st.markdown("#### Fiche au format JSON")
        st.code(
            json.dumps(entite.to_json_dict(), ensure_ascii=False, indent=2),
            language="json",
        )


def _creer(cx: sqlite3.Connection) -> None:
    types = entity_manager.types_entites(cx)
    with st.form("creation_fiche"):
        colonnes = st.columns(2)
        with colonnes[0]:
            entity_type = st.selectbox(
                "Type d'entité", list(types), format_func=lambda c: f"{types[c]} ({c})"
            )
            nom = st.text_input("Nom canonique *")
            identifiant = st.text_input(
                "Identifiant (laisser vide pour une attribution automatique)",
                placeholder="PERSON_0001",
            )
        with colonnes[1]:
            statuts = list(STATUTS_ENTITE)
            statut = st.selectbox(
                "Statut de validation",
                statuts,
                index=statuts.index("brouillon"),
                format_func=lambda s: STATUTS_ENTITE[s],
            )
            description = st.text_input("Description")
        variantes = st.text_area("Variantes (une par ligne)", height=100)
        sources = st.text_area("Sources documentaires (une par ligne)", height=80)
        envoye = st.form_submit_button("Créer la fiche", type="primary")
    if envoye:
        try:
            entite = entity_manager.creer_entite(
                cx,
                entity_type=entity_type,
                canonical_name=nom,
                description=description,
                variants=[v.strip() for v in variantes.splitlines() if v.strip()],
                sources=[s.strip() for s in sources.splitlines() if s.strip()],
                validation_status=statut,
                entity_id=identifiant.strip() or None,
            )
            st.success(f"Fiche {entite.entity_id} créée.")
        except entity_manager.ErreurEntite as exc:
            message_erreur(exc)


def _doublons(cx: sqlite3.Connection) -> None:
    st.caption(
        "Les doublons sont seulement signalés : aucune fusion n'est effectuée "
        "automatiquement. La fusion ci-dessous reporte les mentions de la fiche "
        "source vers la fiche cible, puis supprime la source."
    )
    seuil = st.slider("Seuil de similarité", 0.70, 1.00, 0.86, 0.01)
    doublons = entity_manager.detecter_doublons(cx, seuil)
    if not doublons:
        st.success("Aucun doublon potentiel détecté avec ce seuil.")
        return
    st.warning(f"{len(doublons)} couple(s) à examiner.")
    for index, doublon in enumerate(doublons[:50]):
        a, b = doublon["a"], doublon["b"]
        with st.expander(
            f"{a.canonical_name} [{a.entity_id}] ↔ {b.canonical_name} [{b.entity_id}] "
            f"— score {doublon['score']}"
        ):
            colonnes = st.columns(2)
            for colonne, entite in zip(colonnes, (a, b)):
                with colonne:
                    st.markdown(f"**{entite.entity_id}**")
                    st.write(f"Nom : {entite.canonical_name}")
                    st.write(f"Variantes : {', '.join(entite.variants) or '—'}")
                    st.write(f"Description : {entite.description or '—'}")
                    st.write(
                        f"Statut : {STATUTS_ENTITE.get(entite.validation_status, '')}"
                    )
            st.caption(doublon["motif"])
            choix = st.radio(
                "Sens de la fusion",
                [
                    f"Conserver {a.entity_id} (fusionner {b.entity_id} dedans)",
                    f"Conserver {b.entity_id} (fusionner {a.entity_id} dedans)",
                ],
                key=f"fusion_sens_{index}",
            )
            coche = st.checkbox(
                "Je confirme cette fusion (opération irréversible).",
                key=f"fusion_conf_{index}",
            )
            if st.button("Fusionner", key=f"fusion_btn_{index}", disabled=not coche):
                source, cible = (b, a) if choix.startswith(f"Conserver {a.entity_id}") else (a, b)
                try:
                    rapport = entity_manager.fusionner(cx, source.entity_id, cible.entity_id)
                    st.success(
                        f"Fusion effectuée : {rapport['annotations_transferees']} "
                        f"mention(s) reportée(s) sur {cible.entity_id}."
                    )
                    st.rerun()
                except entity_manager.ErreurEntite as exc:
                    message_erreur(exc)
