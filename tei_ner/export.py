"""Génération des exports : référentiel JSON, corpus TEI, jeu d'entraînement JSONL.

Traçabilité : chaque enregistrement exporté porte l'identifiant du document
source, l'identifiant de l'annotation et l'identifiant de la fiche d'entité.
Un manifeste récapitule la date, les filtres appliqués et les conventions.
"""

from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import annotation as annotation_module
import corpus
import entity_manager
import tei_parser
from database import DOSSIER_EXPORTS, journaliser
from models import UNICODE_NORMALISATION, maintenant

VERSION_EXPORT = "1.0"

# Statuts considérés comme « validés » pour l'export séparé.
STATUTS_VALIDES = ("validee",)


def _filtrer(
    annotations: Iterable[dict[str, Any]], portee: str
) -> list[dict[str, Any]]:
    """portee : 'validees', 'non_validees' ou 'toutes'."""
    annotations = list(annotations)
    if portee == "validees":
        return [a for a in annotations if a["statut"] in STATUTS_VALIDES]
    if portee == "non_validees":
        return [a for a in annotations if a["statut"] not in STATUTS_VALIDES]
    return annotations


def manifeste(
    cx: sqlite3.Connection, portee: str, options: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "application": "Application d'annotation et de gestion des entités nommées XML-TEI",
        "version_export": VERSION_EXPORT,
        "date_export": maintenant(),
        "portee": portee,
        "convention_offsets": {
            "unite": "point de code Unicode",
            "normalisation": UNICODE_NORMALISATION,
            "intervalle": "semi-ouvert [start, end[",
            "texte_de_reference": (
                "texte brut obtenu par parcours en ordre documentaire de l'élément "
                "<text> du fichier TEI, espaces consécutifs réduits à une espace, "
                "éléments de bloc séparés par un saut de ligne"
            ),
        },
        "statuts_consideres_valides": list(STATUTS_VALIDES),
        "options": options or {},
    }


# --------------------------------------------------------------------------
# 1. Référentiel des entités (JSON)
# --------------------------------------------------------------------------
def referentiel_json(
    cx: sqlite3.Connection, portee: str = "toutes", avec_occurrences: bool = True
) -> dict[str, Any]:
    entites = entity_manager.lister_entites(cx)
    if portee == "validees":
        entites = [e for e in entites if e.validation_status == "validee"]
    elif portee == "non_validees":
        entites = [e for e in entites if e.validation_status != "validee"]

    comptes: dict[str, int] = {}
    if avec_occurrences:
        for ligne in cx.execute(
            "SELECT entity_id, COUNT(*) AS n FROM annotations"
            " WHERE entity_id IS NOT NULL GROUP BY entity_id"
        ):
            comptes[ligne["entity_id"]] = ligne["n"]

    fiches = []
    for entite in entites:
        fiche = entite.to_json_dict()
        if avec_occurrences:
            fiche["nb_occurrences"] = comptes.get(entite.entity_id, 0)
            fiche["documents"] = [
                ligne["document_id"]
                for ligne in cx.execute(
                    "SELECT DISTINCT document_id FROM annotations WHERE entity_id = ?"
                    " ORDER BY document_id",
                    (entite.entity_id,),
                )
            ]
        fiches.append(fiche)

    return {
        "manifeste": manifeste(cx, portee, {"avec_occurrences": avec_occurrences}),
        "nb_entites": len(fiches),
        "entites": fiches,
    }


# --------------------------------------------------------------------------
# 2. Corpus annoté (XML-TEI)
# --------------------------------------------------------------------------
def documents_tei(
    cx: sqlite3.Connection,
    portee: str = "toutes",
    mode: str = "mixte",
    documents: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Produit le XML enrichi de chaque document retenu."""
    resultats: list[dict[str, Any]] = []
    dictionnaire = entity_manager.dictionnaire_entites(cx)
    for document in corpus.lister_documents(cx):
        if document.statut == "invalide":
            continue
        if documents and document.id not in documents:
            continue
        complet = corpus.lire_document(cx, document.id)  # type: ignore[arg-type]
        if complet is None:
            continue
        annotations = _filtrer(
            annotation_module.annotations_dict(cx, complet.id), portee
        )
        try:
            analyse = corpus.analyse_du_document(complet)
        except tei_parser.ErreurTEI as exc:
            resultats.append(
                {
                    "document_id": complet.id,
                    "nom_fichier": complet.nom_fichier,
                    "erreur": str(exc),
                    "xml": None,
                }
            )
            continue
        utilisees = {
            a["entity_id"]: dictionnaire[a["entity_id"]]
            for a in annotations
            if a.get("entity_id") and a["entity_id"] in dictionnaire
        }
        resultat = tei_parser.exporter_tei(analyse, annotations, utilisees, mode=mode)
        valide, message = tei_parser.valider_xml(resultat.xml)
        resultats.append(
            {
                "document_id": complet.id,
                "nom_fichier": complet.nom_fichier,
                "titre": complet.titre,
                "xml": resultat.xml,
                "nb_annotations": len(annotations),
                "inserees_en_ligne": resultat.inserees,
                "reportees_standoff": len(resultat.reportees),
                "details_reportees": resultat.reportees,
                "xml_valide": valide,
                "message_validation": message,
            }
        )
    return resultats


# --------------------------------------------------------------------------
# 3. Jeu d'entraînement (JSONL)
# --------------------------------------------------------------------------
def lignes_jsonl(
    cx: sqlite3.Connection,
    portee: str = "validees",
    granularite: str = "document",
    documents: list[int] | None = None,
    inclure_non_resolues: bool = False,
) -> list[dict[str, Any]]:
    """Construit les enregistrements du jeu d'entraînement.

    granularite : 'document' (un enregistrement par document) ou
    'paragraphe' (un enregistrement par bloc, recommandé pour l'entraînement).
    """
    enregistrements: list[dict[str, Any]] = []
    for document in corpus.lister_documents(cx):
        if document.statut == "invalide":
            continue
        if documents and document.id not in documents:
            continue
        complet = corpus.lire_document(cx, document.id)  # type: ignore[arg-type]
        if complet is None:
            continue
        annotations = _filtrer(
            annotation_module.annotations_dict(cx, complet.id), portee
        )
        if not inclure_non_resolues:
            annotations = [a for a in annotations if a.get("entity_id")]
        annotations.sort(key=lambda a: (a["debut"], a["fin"]))

        if granularite == "document":
            blocs = [{"debut": 0, "fin": len(complet.texte), "texte": complet.texte}]
        else:
            blocs = annotation_module.paragraphes(complet.texte)

        for index, bloc in enumerate(blocs):
            entites = []
            for ann in annotations:
                if ann["debut"] >= bloc["debut"] and ann["fin"] <= bloc["fin"]:
                    entites.append(
                        {
                            "start": ann["debut"] - bloc["debut"],
                            "end": ann["fin"] - bloc["debut"],
                            "label": ann["label"],
                            "entity_id": ann.get("entity_id"),
                            "text": ann["surface"],
                            "annotation_id": ann["id"],
                            "statut": ann["statut"],
                        }
                    )
            if granularite != "document" and not entites and not bloc["texte"].strip():
                continue
            enregistrements.append(
                {
                    "id": f"doc{complet.id}-{index}",
                    "text": bloc["texte"],
                    "entities": entites,
                    "meta": {
                        "document_id": complet.id,
                        "nom_fichier": complet.nom_fichier,
                        "titre": complet.titre,
                        "offset_dans_document": bloc["debut"],
                        "granularite": granularite,
                    },
                }
            )
    return enregistrements


def verifier_jsonl(enregistrements: list[dict[str, Any]]) -> list[str]:
    """Contrôle de cohérence des offsets du JSONL produit."""
    problemes: list[str] = []
    for enregistrement in enregistrements:
        texte = enregistrement["text"]
        for entite in enregistrement["entities"]:
            debut, fin = entite["start"], entite["end"]
            if not (0 <= debut < fin <= len(texte)):
                problemes.append(
                    f"{enregistrement['id']} : intervalle [{debut},{fin}[ hors texte."
                )
            elif texte[debut:fin] != entite["text"]:
                problemes.append(
                    f"{enregistrement['id']} : « {texte[debut:fin]} » attendu "
                    f"« {entite['text']} »."
                )
    return problemes


def serialiser_jsonl(enregistrements: list[dict[str, Any]]) -> str:
    return "\n".join(
        json.dumps(e, ensure_ascii=False) for e in enregistrements
    ) + ("\n" if enregistrements else "")


# --------------------------------------------------------------------------
# Archive complète
# --------------------------------------------------------------------------
def construire_archive(
    cx: sqlite3.Connection,
    portee: str = "toutes",
    mode_tei: str = "mixte",
    granularite_jsonl: str = "paragraphe",
    inclure_originaux: bool = True,
    documents: list[int] | None = None,
) -> bytes:
    """Archive ZIP contenant les trois exports, les originaux et le manifeste."""
    tampon = io.BytesIO()
    avec_separation = portee == "toutes"
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as archive:
        # Manifeste
        info = manifeste(
            cx,
            portee,
            {
                "mode_tei": mode_tei,
                "granularite_jsonl": granularite_jsonl,
                "documents": documents or "tous",
            },
        )
        info["contenu"] = {
            "referentiel/": "référentiel des entités au format JSON",
            "tei/": "corpus réexporté en XML-TEI enrichi",
            "jsonl/": "jeu de données pour la reconnaissance d'entités nommées",
            "originaux/": "copie conforme des fichiers importés",
        }
        archive.writestr(
            "manifeste.json", json.dumps(info, ensure_ascii=False, indent=2)
        )

        # 1. Référentiel
        portees_ref = ["validees", "non_validees"] if avec_separation else [portee]
        for p in portees_ref:
            archive.writestr(
                f"referentiel/entites-{p}.json",
                json.dumps(referentiel_json(cx, p), ensure_ascii=False, indent=2),
            )
        archive.writestr(
            "referentiel/entites-toutes.json",
            json.dumps(referentiel_json(cx, "toutes"), ensure_ascii=False, indent=2),
        )

        # 2. TEI
        rapport_tei = []
        for resultat in documents_tei(cx, portee, mode_tei, documents):
            if resultat.get("xml"):
                archive.writestr(f"tei/{resultat['nom_fichier']}", resultat["xml"])
            rapport_tei.append(
                {
                    cle: valeur
                    for cle, valeur in resultat.items()
                    if cle not in ("xml", "details_reportees")
                }
            )
        archive.writestr(
            "tei/rapport-export.json",
            json.dumps(rapport_tei, ensure_ascii=False, indent=2),
        )

        # 3. JSONL
        portees_jsonl = ["validees", "non_validees"] if avec_separation else [portee]
        for p in portees_jsonl:
            enregistrements = lignes_jsonl(cx, p, granularite_jsonl, documents)
            archive.writestr(
                f"jsonl/corpus-{p}.jsonl", serialiser_jsonl(enregistrements)
            )
            problemes = verifier_jsonl(enregistrements)
            if problemes:
                archive.writestr(
                    f"jsonl/corpus-{p}-anomalies.txt", "\n".join(problemes)
                )

        # 4. Originaux
        if inclure_originaux:
            for document in corpus.lister_documents(cx):
                if document.statut == "invalide":
                    continue
                if documents and document.id not in documents:
                    continue
                complet = corpus.lire_document(cx, document.id)  # type: ignore[arg-type]
                if complet and complet.xml_source:
                    archive.writestr(
                        f"originaux/{complet.nom_fichier}", complet.xml_source
                    )

    journaliser(cx, "export_archive", f"portée={portee}, mode TEI={mode_tei}")
    return tampon.getvalue()


def ecrire_archive(
    cx: sqlite3.Connection, dossier: str | Path | None = None, **options: Any
) -> Path:
    cible_dossier = Path(dossier) if dossier else DOSSIER_EXPORTS
    cible_dossier.mkdir(parents=True, exist_ok=True)
    horodatage = datetime.now().strftime("%Y%m%d-%H%M%S")
    cible = cible_dossier / f"export-{horodatage}.zip"
    cible.write_bytes(construire_archive(cx, **options))
    return cible
