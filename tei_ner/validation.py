"""Contrôles qualité du corpus annoté.

Chaque contrôle renvoie une liste d'alertes. Aucune correction n'est
appliquée automatiquement : les fonctions `corriger_*` ne s'exécutent
qu'à la demande explicite de l'usager depuis la page « Validation ».
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Any, Callable

import entity_manager
from database import transaction
from models import Alerte, STATUTS_ANNOTATION, STATUTS_ENTITE, maintenant


# --------------------------------------------------------------------------
# Contrôles
# --------------------------------------------------------------------------
def controle_identifiants(cx: sqlite3.Connection) -> list[Alerte]:
    """Unicité et forme des identifiants d'entités."""
    alertes: list[Alerte] = []
    # L'unicité est garantie par la clé primaire ; on vérifie la forme et
    # les collisions de casse, qui échapperaient à SQLite.
    vus: dict[str, str] = {}
    for ligne in cx.execute("SELECT entity_id, entity_type FROM entites"):
        entity_id = ligne["entity_id"]
        if not entity_manager.MOTIF_ID.match(entity_id):
            alertes.append(
                Alerte(
                    code="id_forme",
                    niveau="avertissement",
                    message=f"L'identifiant « {entity_id} » ne suit pas la forme TYPE_0000.",
                    entity_id=entity_id,
                )
            )
        if not entity_id.startswith(ligne["entity_type"] + "_"):
            alertes.append(
                Alerte(
                    code="id_prefixe",
                    niveau="avertissement",
                    message=(
                        f"L'identifiant « {entity_id} » ne correspond pas au type "
                        f"{ligne['entity_type']}."
                    ),
                    entity_id=entity_id,
                )
            )
        minuscule = entity_id.lower()
        if minuscule in vus:
            alertes.append(
                Alerte(
                    code="id_collision_casse",
                    niveau="erreur",
                    message=(
                        f"Les identifiants « {vus[minuscule]} » et « {entity_id} » "
                        "ne diffèrent que par la casse."
                    ),
                    entity_id=entity_id,
                )
            )
        vus[minuscule] = entity_id
    return alertes


def controle_entites_referencees(cx: sqlite3.Connection) -> list[Alerte]:
    """Les annotations pointent-elles vers une fiche existante ?"""
    alertes: list[Alerte] = []
    lignes = cx.execute(
        "SELECT a.id, a.entity_id, a.document_id, a.surface FROM annotations a"
        " LEFT JOIN entites e ON e.entity_id = a.entity_id"
        " WHERE a.entity_id IS NOT NULL AND e.entity_id IS NULL"
    ).fetchall()
    for ligne in lignes:
        alertes.append(
            Alerte(
                code="entite_absente",
                niveau="erreur",
                message=(
                    f"L'annotation {ligne['id']} (« {ligne['surface']} ») référence "
                    f"l'entité inexistante {ligne['entity_id']}."
                ),
                annotation_id=ligne["id"],
                document_id=ligne["document_id"],
                entity_id=ligne["entity_id"],
                correction="Délier l'annotation et la marquer « non résolue ».",
            )
        )
    return alertes


def controle_coherence_types(cx: sqlite3.Connection) -> list[Alerte]:
    """Le type de l'annotation doit correspondre au type de l'entité liée."""
    alertes: list[Alerte] = []
    lignes = cx.execute(
        "SELECT a.id, a.label, a.surface, a.document_id, e.entity_id, e.entity_type"
        " FROM annotations a JOIN entites e ON e.entity_id = a.entity_id"
        " WHERE a.label <> e.entity_type"
    ).fetchall()
    for ligne in lignes:
        alertes.append(
            Alerte(
                code="type_incoherent",
                niveau="erreur",
                message=(
                    f"L'annotation {ligne['id']} (« {ligne['surface']} ») est de type "
                    f"{ligne['label']} mais l'entité {ligne['entity_id']} est de type "
                    f"{ligne['entity_type']}."
                ),
                annotation_id=ligne["id"],
                document_id=ligne["document_id"],
                entity_id=ligne["entity_id"],
                correction=f"Aligner le type de l'annotation sur {ligne['entity_type']}.",
                donnees={"type_cible": ligne["entity_type"]},
            )
        )
    return alertes


def controle_positions(cx: sqlite3.Connection) -> list[Alerte]:
    """Validité des positions de caractères et concordance de la surface."""
    alertes: list[Alerte] = []
    textes = {
        ligne["id"]: ligne["texte"]
        for ligne in cx.execute("SELECT id, texte FROM documents")
    }
    for ligne in cx.execute("SELECT * FROM annotations ORDER BY document_id, debut"):
        texte = textes.get(ligne["document_id"])
        if texte is None:
            alertes.append(
                Alerte(
                    code="document_absent",
                    niveau="erreur",
                    message=f"L'annotation {ligne['id']} ne se rattache à aucun document.",
                    annotation_id=ligne["id"],
                    correction="Supprimer l'annotation orpheline.",
                )
            )
            continue
        debut, fin = ligne["debut"], ligne["fin"]
        if not (0 <= debut < fin <= len(texte)):
            alertes.append(
                Alerte(
                    code="position_invalide",
                    niveau="erreur",
                    message=(
                        f"L'annotation {ligne['id']} porte sur l'intervalle "
                        f"[{debut}, {fin}[ hors du texte (longueur {len(texte)})."
                    ),
                    annotation_id=ligne["id"],
                    document_id=ligne["document_id"],
                    correction="Supprimer l'annotation.",
                )
            )
            continue
        reel = texte[debut:fin]
        if reel != ligne["surface"]:
            alertes.append(
                Alerte(
                    code="surface_divergente",
                    niveau="erreur",
                    message=(
                        f"L'annotation {ligne['id']} enregistre « {ligne['surface']} » "
                        f"alors que le texte contient « {reel} »."
                    ),
                    annotation_id=ligne["id"],
                    document_id=ligne["document_id"],
                    correction="Recopier la chaîne réellement présente dans le texte.",
                    donnees={"surface_cible": reel},
                )
            )
        if reel != reel.strip():
            alertes.append(
                Alerte(
                    code="bornes_blanches",
                    niveau="avertissement",
                    message=(
                        f"L'annotation {ligne['id']} commence ou se termine par une espace."
                    ),
                    annotation_id=ligne["id"],
                    document_id=ligne["document_id"],
                    correction="Resserrer les bornes sur le texte significatif.",
                )
            )
    return alertes


def controle_chevauchements(cx: sqlite3.Connection) -> list[Alerte]:
    """Annotations qui se chevauchent dans un même document."""
    alertes: list[Alerte] = []
    par_document: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for ligne in cx.execute(
        "SELECT * FROM annotations ORDER BY document_id, debut, fin"
    ):
        par_document[ligne["document_id"]].append(ligne)
    for document_id, lignes in par_document.items():
        for i, courante in enumerate(lignes):
            for suivante in lignes[i + 1 :]:
                if suivante["debut"] >= courante["fin"]:
                    break
                imbriquee = (
                    suivante["debut"] >= courante["debut"]
                    and suivante["fin"] <= courante["fin"]
                )
                alertes.append(
                    Alerte(
                        code="chevauchement",
                        niveau="avertissement" if imbriquee else "erreur",
                        message=(
                            f"Les annotations {courante['id']} (« {courante['surface']} », "
                            f"[{courante['debut']},{courante['fin']}[) et {suivante['id']} "
                            f"(« {suivante['surface']} », [{suivante['debut']},"
                            f"{suivante['fin']}[) se chevauchent."
                        ),
                        annotation_id=suivante["id"],
                        document_id=document_id,
                        correction="Supprimer l'annotation la plus courte.",
                        donnees={
                            "autre_id": courante["id"],
                            "imbriquee": imbriquee,
                            "id_plus_courte": (
                                suivante["id"]
                                if (suivante["fin"] - suivante["debut"])
                                <= (courante["fin"] - courante["debut"])
                                else courante["id"]
                            ),
                        },
                    )
                )
    return alertes


def controle_mentions_ambigues(cx: sqlite3.Connection) -> list[Alerte]:
    """Surfaces identiques reliées à plusieurs entités différentes."""
    alertes: list[Alerte] = []
    lignes = cx.execute(
        "SELECT surface, label, COUNT(DISTINCT entity_id) AS n,"
        " GROUP_CONCAT(DISTINCT entity_id) AS liste FROM annotations"
        " WHERE entity_id IS NOT NULL GROUP BY surface, label HAVING n > 1"
    ).fetchall()
    for ligne in lignes:
        alertes.append(
            Alerte(
                code="mention_ambigue",
                niveau="avertissement",
                message=(
                    f"La mention « {ligne['surface']} » ({ligne['label']}) est reliée à "
                    f"{ligne['n']} entités : {ligne['liste']}."
                ),
                correction="Marquer ces annotations comme ambiguës pour arbitrage.",
                donnees={"surface": ligne["surface"], "label": ligne["label"]},
            )
        )
    return alertes


def controle_champs_obligatoires(cx: sqlite3.Connection) -> list[Alerte]:
    """Champs indispensables des fiches d'entités et des annotations."""
    alertes: list[Alerte] = []
    types_connus = set(entity_manager.types_entites(cx))
    for ligne in cx.execute("SELECT * FROM entites"):
        manques = []
        if not (ligne["canonical_name"] or "").strip():
            manques.append("nom canonique")
        if ligne["entity_type"] not in types_connus:
            manques.append(f"type inconnu ({ligne['entity_type']})")
        if ligne["validation_status"] not in STATUTS_ENTITE:
            manques.append(f"statut inconnu ({ligne['validation_status']})")
        if manques:
            alertes.append(
                Alerte(
                    code="fiche_incomplete",
                    niveau="erreur",
                    message=(
                        f"La fiche {ligne['entity_id']} est incomplète : "
                        + ", ".join(manques)
                        + "."
                    ),
                    entity_id=ligne["entity_id"],
                )
            )
        if ligne["validation_status"] == "validee" and not (ligne["description"] or "").strip():
            alertes.append(
                Alerte(
                    code="description_absente",
                    niveau="information",
                    message=(
                        f"La fiche validée {ligne['entity_id']} n'a pas de description."
                    ),
                    entity_id=ligne["entity_id"],
                )
            )
    for ligne in cx.execute("SELECT * FROM annotations"):
        if ligne["statut"] not in STATUTS_ANNOTATION:
            alertes.append(
                Alerte(
                    code="statut_inconnu",
                    niveau="erreur",
                    message=(
                        f"L'annotation {ligne['id']} porte le statut inconnu "
                        f"« {ligne['statut']} »."
                    ),
                    annotation_id=ligne["id"],
                    correction="Remettre le statut à « à vérifier ».",
                )
            )
        if ligne["label"] not in types_connus:
            alertes.append(
                Alerte(
                    code="label_inconnu",
                    niveau="erreur",
                    message=(
                        f"L'annotation {ligne['id']} utilise le type inconnu "
                        f"« {ligne['label']} »."
                    ),
                    annotation_id=ligne["id"],
                )
            )
    return alertes


def controle_non_resolues(cx: sqlite3.Connection) -> list[Alerte]:
    """Mentions sans entité associée."""
    alertes: list[Alerte] = []
    lignes = cx.execute(
        "SELECT id, document_id, surface, label FROM annotations"
        " WHERE entity_id IS NULL ORDER BY document_id, debut"
    ).fetchall()
    for ligne in lignes:
        alertes.append(
            Alerte(
                code="non_resolue",
                niveau="information",
                message=(
                    f"L'annotation {ligne['id']} (« {ligne['surface']} », "
                    f"{ligne['label']}) n'est reliée à aucune entité."
                ),
                annotation_id=ligne["id"],
                document_id=ligne["document_id"],
            )
        )
    return alertes


def controle_doublons_entites(cx: sqlite3.Connection) -> list[Alerte]:
    """Signale les fiches potentiellement redondantes, sans jamais fusionner."""
    alertes: list[Alerte] = []
    for doublon in entity_manager.detecter_doublons(cx):
        alertes.append(
            Alerte(
                code="doublon_entite",
                niveau="avertissement",
                message=(
                    f"{doublon['a'].entity_id} (« {doublon['a'].canonical_name} ») et "
                    f"{doublon['b'].entity_id} (« {doublon['b'].canonical_name} ») : "
                    f"{doublon['motif']} (score {doublon['score']})."
                ),
                entity_id=doublon["a"].entity_id,
                correction="Fusion manuelle à examiner dans le référentiel.",
                donnees={"autre": doublon["b"].entity_id, "score": doublon["score"]},
            )
        )
    return alertes


CONTROLES: dict[str, tuple[str, Callable[[sqlite3.Connection], list[Alerte]]]] = {
    "identifiants": ("Unicité et forme des identifiants", controle_identifiants),
    "entites_referencees": ("Existence des entités référencées", controle_entites_referencees),
    "coherence_types": ("Cohérence type d'entité / type d'annotation", controle_coherence_types),
    "positions": ("Validité des positions de caractères", controle_positions),
    "chevauchements": ("Annotations qui se chevauchent", controle_chevauchements),
    "mentions_ambigues": ("Mentions identiques reliées à plusieurs entités", controle_mentions_ambigues),
    "champs_obligatoires": ("Champs obligatoires", controle_champs_obligatoires),
    "non_resolues": ("Mentions non résolues", controle_non_resolues),
    "doublons_entites": ("Doublons potentiels d'entités", controle_doublons_entites),
}


def executer_controles(
    cx: sqlite3.Connection, codes: list[str] | None = None
) -> list[Alerte]:
    codes = codes or list(CONTROLES)
    alertes: list[Alerte] = []
    for code in codes:
        if code in CONTROLES:
            alertes.extend(CONTROLES[code][1](cx))
    ordre = {"erreur": 0, "avertissement": 1, "information": 2}
    alertes.sort(key=lambda a: (ordre.get(a.niveau, 3), a.code))
    return alertes


def resume(alertes: list[Alerte]) -> dict[str, int]:
    compte = {"erreur": 0, "avertissement": 0, "information": 0}
    for alerte in alertes:
        compte[alerte.niveau] = compte.get(alerte.niveau, 0) + 1
    return compte


# --------------------------------------------------------------------------
# Corrections — uniquement sur demande explicite
# --------------------------------------------------------------------------
def corrections_possibles(alertes: list[Alerte]) -> list[Alerte]:
    return [a for a in alertes if a.correction]


def appliquer_corrections(cx: sqlite3.Connection, alertes: list[Alerte]) -> dict[str, int]:
    """Applique les corrections proposées pour les alertes sélectionnées."""
    compte: dict[str, int] = defaultdict(int)
    horodatage = maintenant()
    with transaction(cx):
        for alerte in alertes:
            if alerte.code == "entite_absente" and alerte.annotation_id:
                cx.execute(
                    "UPDATE annotations SET entity_id = NULL, statut = 'non_resolue',"
                    " modifie_le = ? WHERE id = ?",
                    (horodatage, alerte.annotation_id),
                )
                compte["annotations_deliees"] += 1
            elif alerte.code == "type_incoherent" and alerte.annotation_id:
                cx.execute(
                    "UPDATE annotations SET label = ?, modifie_le = ? WHERE id = ?",
                    (alerte.donnees["type_cible"], horodatage, alerte.annotation_id),
                )
                compte["types_alignes"] += 1
            elif alerte.code == "surface_divergente" and alerte.annotation_id:
                cx.execute(
                    "UPDATE annotations SET surface = ?, modifie_le = ? WHERE id = ?",
                    (alerte.donnees["surface_cible"], horodatage, alerte.annotation_id),
                )
                compte["surfaces_corrigees"] += 1
            elif alerte.code in ("position_invalide", "document_absent") and alerte.annotation_id:
                cx.execute("DELETE FROM annotations WHERE id = ?", (alerte.annotation_id,))
                compte["annotations_supprimees"] += 1
            elif alerte.code == "bornes_blanches" and alerte.annotation_id:
                ligne = cx.execute(
                    "SELECT a.id, a.debut, a.fin, d.texte FROM annotations a"
                    " JOIN documents d ON d.id = a.document_id WHERE a.id = ?",
                    (alerte.annotation_id,),
                ).fetchone()
                if ligne:
                    texte = ligne["texte"]
                    debut, fin = ligne["debut"], ligne["fin"]
                    while debut < fin and texte[debut].isspace():
                        debut += 1
                    while fin > debut and texte[fin - 1].isspace():
                        fin -= 1
                    cx.execute(
                        "UPDATE annotations SET debut = ?, fin = ?, surface = ?,"
                        " modifie_le = ? WHERE id = ?",
                        (debut, fin, texte[debut:fin], horodatage, alerte.annotation_id),
                    )
                    compte["bornes_resserrees"] += 1
            elif alerte.code == "chevauchement":
                cible = alerte.donnees.get("id_plus_courte")
                if cible:
                    cx.execute("DELETE FROM annotations WHERE id = ?", (cible,))
                    compte["chevauchements_resolus"] += 1
            elif alerte.code == "mention_ambigue":
                cx.execute(
                    "UPDATE annotations SET statut = 'ambigue', modifie_le = ?"
                    " WHERE surface = ? AND label = ? AND entity_id IS NOT NULL",
                    (horodatage, alerte.donnees["surface"], alerte.donnees["label"]),
                )
                compte["mentions_marquees_ambigues"] += 1
            elif alerte.code == "statut_inconnu" and alerte.annotation_id:
                cx.execute(
                    "UPDATE annotations SET statut = 'a_verifier', modifie_le = ?"
                    " WHERE id = ?",
                    (horodatage, alerte.annotation_id),
                )
                compte["statuts_reinitialises"] += 1
    return dict(compte)
