"""Import et consultation du corpus XML-TEI.

Les fichiers d'origine ne sont jamais modifiés : leur contenu est copié en
base de données, et toute production de XML enrichi passe par export.py.
"""

from __future__ import annotations

import html
import json
import sqlite3
from pathlib import Path
from typing import Any

import tei_parser
from database import journaliser, transaction
from models import Document, maintenant


class ErreurImport(Exception):
    """Import impossible."""


def _document_depuis_ligne(ligne: sqlite3.Row, avec_source: bool = True) -> Document:
    try:
        metadonnees = json.loads(ligne["metadonnees"] or "{}")
    except json.JSONDecodeError:
        metadonnees = {}
    return Document(
        id=ligne["id"],
        nom_fichier=ligne["nom_fichier"],
        titre=ligne["titre"],
        tei_id=ligne["tei_id"],
        empreinte=ligne["empreinte"],
        texte=ligne["texte"],
        metadonnees=metadonnees,
        xml_source=ligne["xml_source"] if avec_source else "",
        statut=ligne["statut"],
        message_erreur=ligne["message_erreur"],
        nb_caracteres=ligne["nb_caracteres"],
        cree_le=ligne["cree_le"],
        modifie_le=ligne["modifie_le"],
    )


def lister_documents(cx: sqlite3.Connection) -> list[Document]:
    lignes = cx.execute(
        "SELECT id, nom_fichier, titre, tei_id, empreinte, '' AS texte, metadonnees,"
        " '' AS xml_source, statut, message_erreur, nb_caracteres, cree_le, modifie_le"
        " FROM documents ORDER BY titre, nom_fichier"
    ).fetchall()
    return [_document_depuis_ligne(l, avec_source=False) for l in lignes]


def lire_document(cx: sqlite3.Connection, document_id: int) -> Document | None:
    ligne = cx.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    return _document_depuis_ligne(ligne) if ligne else None


def importer_fichier(
    cx: sqlite3.Connection,
    contenu: bytes | str,
    nom_fichier: str,
    reprendre_annotations_tei: bool = True,
) -> dict[str, Any]:
    """Importe un fichier XML-TEI. Renvoie un compte rendu détaillé."""
    compte_rendu: dict[str, Any] = {
        "fichier": nom_fichier,
        "statut": "erreur",
        "document_id": None,
        "message": "",
        "annotations_detectees": 0,
    }
    try:
        analyse = tei_parser.analyser(contenu, nom_fichier)
    except tei_parser.ErreurTEI as exc:
        compte_rendu["message"] = str(exc)
        compte_rendu["statut"] = "invalide"
        _enregistrer_echec(cx, nom_fichier, str(exc))
        return compte_rendu

    existant = cx.execute(
        "SELECT id, nom_fichier FROM documents WHERE empreinte = ?",
        (analyse.empreinte,),
    ).fetchone()
    if existant:
        compte_rendu["statut"] = "doublon"
        compte_rendu["document_id"] = existant["id"]
        compte_rendu["message"] = (
            f"Fichier déjà présent dans le corpus sous le nom « {existant['nom_fichier']} »."
        )
        return compte_rendu

    horodatage = maintenant()
    with transaction(cx):
        curseur = cx.execute(
            "INSERT INTO documents(nom_fichier, titre, tei_id, empreinte, texte,"
            " metadonnees, xml_source, statut, message_erreur, nb_caracteres,"
            " cree_le, modifie_le) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                nom_fichier,
                analyse.titre,
                analyse.tei_id,
                analyse.empreinte,
                analyse.texte,
                json.dumps(analyse.metadonnees, ensure_ascii=False),
                analyse.xml_source,
                "importe",
                None,
                len(analyse.texte),
                horodatage,
                horodatage,
            ),
        )
        document_id = int(curseur.lastrowid)

        if reprendre_annotations_tei:
            for item in analyse.annotations_existantes:
                cx.execute(
                    "INSERT INTO annotations(document_id, entity_id, label, debut, fin,"
                    " surface, statut, origine, note, tei_xml_id, cree_le, modifie_le)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        document_id,
                        None,
                        item["label"],
                        item["debut"],
                        item["fin"],
                        item["surface"],
                        "non_resolue",
                        "tei",
                        f"Détectée depuis <{item['balise']}>"
                        + (f" ref={item['ref']}" if item.get("ref") else ""),
                        item.get("xml_id"),
                        horodatage,
                        horodatage,
                    ),
                )
            compte_rendu["annotations_detectees"] = len(analyse.annotations_existantes)

    compte_rendu["statut"] = "importe"
    compte_rendu["document_id"] = document_id
    compte_rendu["message"] = (
        f"{len(analyse.texte)} caractères, "
        f"{compte_rendu['annotations_detectees']} mention(s) déjà encodée(s)."
    )
    journaliser(cx, "import_tei", f"{nom_fichier} -> document {document_id}")
    return compte_rendu


def _enregistrer_echec(cx: sqlite3.Connection, nom_fichier: str, message: str) -> None:
    """Conserve la trace d'un fichier refusé, sans texte ni source exploitable."""
    horodatage = maintenant()
    empreinte = f"invalide::{nom_fichier}::{horodatage}"
    with transaction(cx):
        cx.execute(
            "INSERT INTO documents(nom_fichier, titre, tei_id, empreinte, texte,"
            " metadonnees, xml_source, statut, message_erreur, nb_caracteres,"
            " cree_le, modifie_le) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                nom_fichier,
                nom_fichier,
                None,
                empreinte,
                "",
                "{}",
                "",
                "invalide",
                message,
                0,
                horodatage,
                horodatage,
            ),
        )
    journaliser(cx, "import_refuse", f"{nom_fichier} : {message}")


def supprimer_document(cx: sqlite3.Connection, document_id: int) -> int:
    nb = cx.execute(
        "SELECT COUNT(*) AS n FROM annotations WHERE document_id = ?", (document_id,)
    ).fetchone()["n"]
    with transaction(cx):
        cx.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    journaliser(cx, "suppression_document", f"document {document_id}")
    return int(nb)


def analyse_du_document(document: Document) -> tei_parser.DocumentTEI:
    """Ré-analyse le XML conservé en base (nécessaire pour l'export en ligne)."""
    return tei_parser.analyser(document.xml_source, document.nom_fichier)


def exporter_original(document: Document, dossier: str | Path) -> Path:
    """Écrit une copie conforme du fichier d'origine."""
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    cible = dossier / document.nom_fichier
    cible.write_text(document.xml_source, encoding="utf-8")
    return cible


# --------------------------------------------------------------------------
# Affichage
# --------------------------------------------------------------------------
COULEURS = {
    "PERSON": "#b3d4fc",
    "PLACE": "#c8e6c9",
    "ORG": "#ffe0b2",
    "WORK": "#e1bee7",
    "EVENT": "#ffcdd2",
    "OTHER": "#e0e0e0",
}


def couleur(label: str) -> str:
    return COULEURS.get(label, "#e0e0e0")


def texte_balise(
    texte: str,
    annotations: list[dict[str, Any]],
    debut: int = 0,
    fin: int | None = None,
) -> str:
    """Rend un extrait de texte en HTML avec les mentions surlignées.

    Les annotations qui se chevauchent sont affichées dans l'ordre ; en cas
    de chevauchement, seule la première est surlignée (les autres restent
    visibles dans le tableau des annotations).
    """
    fin = len(texte) if fin is None else fin
    extrait = texte[debut:fin]
    pertinentes = sorted(
        [a for a in annotations if a["debut"] < fin and a["fin"] > debut],
        key=lambda a: (a["debut"], -a["fin"]),
    )
    morceaux: list[str] = []
    curseur = debut
    for ann in pertinentes:
        a = max(ann["debut"], debut)
        b = min(ann["fin"], fin)
        if a < curseur:
            continue
        morceaux.append(html.escape(texte[curseur:a]))
        etiquette = ann.get("label", "OTHER")
        reference = ann.get("entity_id") or "non résolue"
        statut = ann.get("statut", "")
        bordure = "2px solid #d32f2f" if statut in ("ambigue", "non_resolue") else "1px solid #9e9e9e"
        morceaux.append(
            f'<span style="background:{couleur(etiquette)};border:{bordure};'
            f'border-radius:3px;padding:0 2px;" '
            f'title="{html.escape(etiquette)} — {html.escape(str(reference))} '
            f'({html.escape(statut)})">{html.escape(texte[a:b])}'
            f'<sub style="font-size:0.7em;color:#444;">{html.escape(etiquette[:2])}</sub></span>'
        )
        curseur = b
    morceaux.append(html.escape(texte[curseur:fin]))
    rendu = "".join(morceaux).replace("\n", "<br/>")
    return (
        '<div style="line-height:1.9;font-size:1.02rem;white-space:normal;'
        'font-family:Georgia,serif;">' + rendu + "</div>"
    )
