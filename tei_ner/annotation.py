"""Logique d'annotation : création, modification, recherche d'occurrences.

Limite technique connue (voir README) : Streamlit ne donne pas accès à la
sélection de texte effectuée à la souris dans le navigateur. L'application
propose donc deux mécanismes de sélection fiables et équivalents :

1. la sélection par bornes de mots (découpage du texte en jetons positionnés) ;
2. la recherche d'occurrences d'une chaîne, avec contexte, et annotation
   unitaire ou en lot.

Dans les deux cas, les positions de caractères sont calculées par le
programme : l'usager ne saisit jamais d'offsets à la main.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Iterable

from database import transaction
from models import Annotation, maintenant

MOTIF_JETON = re.compile(r"\w+(?:['’-]\w+)*|[^\s\w]", re.UNICODE)


class ErreurAnnotation(Exception):
    """Annotation invalide."""


# --------------------------------------------------------------------------
# Lecture
# --------------------------------------------------------------------------
def _depuis_ligne(ligne: sqlite3.Row) -> Annotation:
    return Annotation(
        id=ligne["id"],
        document_id=ligne["document_id"],
        entity_id=ligne["entity_id"],
        label=ligne["label"],
        start=ligne["debut"],
        end=ligne["fin"],
        surface=ligne["surface"],
        statut=ligne["statut"],
        origine=ligne["origine"],
        note=ligne["note"] or "",
        tei_xml_id=ligne["tei_xml_id"],
        cree_le=ligne["cree_le"],
        modifie_le=ligne["modifie_le"],
    )


def lister_annotations(
    cx: sqlite3.Connection,
    document_id: int | None = None,
    entity_id: str | None = None,
    statut: str | None = None,
    label: str | None = None,
) -> list[Annotation]:
    conditions: list[str] = []
    params: list[Any] = []
    if document_id is not None:
        conditions.append("document_id = ?")
        params.append(document_id)
    if entity_id is not None:
        conditions.append("entity_id = ?")
        params.append(entity_id)
    if statut:
        conditions.append("statut = ?")
        params.append(statut)
    if label:
        conditions.append("label = ?")
        params.append(label)
    sql = "SELECT * FROM annotations"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY document_id, debut"
    return [_depuis_ligne(l) for l in cx.execute(sql, tuple(params))]


def lire_annotation(cx: sqlite3.Connection, annotation_id: int) -> Annotation | None:
    ligne = cx.execute(
        "SELECT * FROM annotations WHERE id = ?", (annotation_id,)
    ).fetchone()
    return _depuis_ligne(ligne) if ligne else None


def annotations_dict(
    cx: sqlite3.Connection, document_id: int | None = None
) -> list[dict[str, Any]]:
    """Représentation « dictionnaire » utilisée par l'affichage et les exports."""
    return [
        {
            "id": a.id,
            "document_id": a.document_id,
            "entity_id": a.entity_id,
            "label": a.label,
            "debut": a.start,
            "fin": a.end,
            "surface": a.surface,
            "statut": a.statut,
            "origine": a.origine,
            "note": a.note,
        }
        for a in lister_annotations(cx, document_id=document_id)
    ]


def occurrences_entite(cx: sqlite3.Connection, entity_id: str) -> list[dict[str, Any]]:
    """Toutes les occurrences d'une entité, avec le document d'origine."""
    lignes = cx.execute(
        "SELECT a.*, d.titre AS doc_titre, d.nom_fichier AS doc_fichier,"
        " d.texte AS doc_texte FROM annotations a"
        " JOIN documents d ON d.id = a.document_id"
        " WHERE a.entity_id = ? ORDER BY d.titre, a.debut",
        (entity_id,),
    ).fetchall()
    resultats = []
    for ligne in lignes:
        texte = ligne["doc_texte"] or ""
        gauche = texte[max(0, ligne["debut"] - 60) : ligne["debut"]]
        droite = texte[ligne["fin"] : ligne["fin"] + 60]
        resultats.append(
            {
                "id": ligne["id"],
                "document_id": ligne["document_id"],
                "document": ligne["doc_titre"] or ligne["doc_fichier"],
                "debut": ligne["debut"],
                "fin": ligne["fin"],
                "surface": ligne["surface"],
                "statut": ligne["statut"],
                "label": ligne["label"],
                "contexte": f"…{gauche}[{ligne['surface']}]{droite}…",
            }
        )
    return resultats


# --------------------------------------------------------------------------
# Écriture
# --------------------------------------------------------------------------
def creer_annotation(
    cx: sqlite3.Connection,
    document_id: int,
    debut: int,
    fin: int,
    label: str,
    entity_id: str | None = None,
    statut: str | None = None,
    origine: str = "manuelle",
    note: str = "",
    autoriser_doublon: bool = False,
) -> Annotation:
    ligne = cx.execute(
        "SELECT texte FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    if ligne is None:
        raise ErreurAnnotation(f"Document introuvable : {document_id}")
    texte = ligne["texte"]
    if not (0 <= debut < fin <= len(texte)):
        raise ErreurAnnotation(
            f"Positions invalides : [{debut}, {fin}[ hors du texte "
            f"(longueur {len(texte)})."
        )
    surface = texte[debut:fin]
    if not surface.strip():
        raise ErreurAnnotation("La sélection ne contient aucun caractère significatif.")
    if entity_id:
        existe = cx.execute(
            "SELECT 1 FROM entites WHERE entity_id = ?", (entity_id,)
        ).fetchone()
        if not existe:
            raise ErreurAnnotation(f"Entité inconnue : {entity_id}")
    if not autoriser_doublon:
        doublon = cx.execute(
            "SELECT id FROM annotations WHERE document_id = ? AND debut = ? AND fin = ?",
            (document_id, debut, fin),
        ).fetchone()
        if doublon:
            raise ErreurAnnotation(
                f"Une annotation existe déjà exactement à ces positions "
                f"(identifiant {doublon['id']})."
            )
    if statut is None:
        statut = "a_verifier" if entity_id else "non_resolue"
    horodatage = maintenant()
    with transaction(cx):
        curseur = cx.execute(
            "INSERT INTO annotations(document_id, entity_id, label, debut, fin, surface,"
            " statut, origine, note, tei_xml_id, cree_le, modifie_le)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                document_id,
                entity_id,
                label,
                debut,
                fin,
                surface,
                statut,
                origine,
                note,
                None,
                horodatage,
                horodatage,
            ),
        )
        annotation_id = int(curseur.lastrowid)
    return lire_annotation(cx, annotation_id)  # type: ignore[return-value]


def modifier_annotation(cx: sqlite3.Connection, annotation_id: int, **champs: Any) -> Annotation:
    annotation = lire_annotation(cx, annotation_id)
    if annotation is None:
        raise ErreurAnnotation(f"Annotation introuvable : {annotation_id}")
    entity_id = champs.get("entity_id", annotation.entity_id)
    if entity_id:
        existe = cx.execute(
            "SELECT 1 FROM entites WHERE entity_id = ?", (entity_id,)
        ).fetchone()
        if not existe:
            raise ErreurAnnotation(f"Entité inconnue : {entity_id}")
    debut = int(champs.get("debut", annotation.start))
    fin = int(champs.get("fin", annotation.end))
    ligne = cx.execute(
        "SELECT texte FROM documents WHERE id = ?", (annotation.document_id,)
    ).fetchone()
    texte = ligne["texte"] if ligne else ""
    if not (0 <= debut < fin <= len(texte)):
        raise ErreurAnnotation("Positions invalides pour ce document.")
    with transaction(cx):
        cx.execute(
            "UPDATE annotations SET entity_id = ?, label = ?, debut = ?, fin = ?,"
            " surface = ?, statut = ?, note = ?, modifie_le = ? WHERE id = ?",
            (
                entity_id,
                champs.get("label", annotation.label),
                debut,
                fin,
                texte[debut:fin],
                champs.get("statut", annotation.statut),
                champs.get("note", annotation.note) or "",
                maintenant(),
                annotation_id,
            ),
        )
    return lire_annotation(cx, annotation_id)  # type: ignore[return-value]


def supprimer_annotation(cx: sqlite3.Connection, annotation_id: int) -> None:
    with transaction(cx):
        cx.execute("DELETE FROM annotations WHERE id = ?", (annotation_id,))


def supprimer_annotations(cx: sqlite3.Connection, identifiants: Iterable[int]) -> int:
    identifiants = list(identifiants)
    if not identifiants:
        return 0
    with transaction(cx):
        for i in range(0, len(identifiants), 500):
            lot = identifiants[i : i + 500]
            marqueurs = ",".join("?" * len(lot))
            cx.execute(
                f"DELETE FROM annotations WHERE id IN ({marqueurs})",  # noqa: S608
                tuple(lot),
            )
    return len(identifiants)


def changer_statut(cx: sqlite3.Connection, identifiants: Iterable[int], statut: str) -> int:
    identifiants = list(identifiants)
    if not identifiants:
        return 0
    with transaction(cx):
        for i in range(0, len(identifiants), 500):
            lot = identifiants[i : i + 500]
            marqueurs = ",".join("?" * len(lot))
            cx.execute(
                f"UPDATE annotations SET statut = ?, modifie_le = ? "  # noqa: S608
                f"WHERE id IN ({marqueurs})",
                (statut, maintenant(), *lot),
            )
    return len(identifiants)


def relier_entite(
    cx: sqlite3.Connection, identifiants: Iterable[int], entity_id: str
) -> int:
    existe = cx.execute(
        "SELECT entity_type FROM entites WHERE entity_id = ?", (entity_id,)
    ).fetchone()
    if not existe:
        raise ErreurAnnotation(f"Entité inconnue : {entity_id}")
    identifiants = list(identifiants)
    if not identifiants:
        return 0
    with transaction(cx):
        for i in range(0, len(identifiants), 500):
            lot = identifiants[i : i + 500]
            marqueurs = ",".join("?" * len(lot))
            cx.execute(
                f"UPDATE annotations SET entity_id = ?, label = ?, "  # noqa: S608
                f"statut = CASE WHEN statut = 'non_resolue' THEN 'a_verifier' "
                f"ELSE statut END, modifie_le = ? WHERE id IN ({marqueurs})",
                (entity_id, existe["entity_type"], maintenant(), *lot),
            )
    return len(identifiants)


# --------------------------------------------------------------------------
# Aides à la sélection
# --------------------------------------------------------------------------
def jetons(texte: str, debut: int = 0, fin: int | None = None) -> list[dict[str, Any]]:
    """Découpe un extrait en jetons positionnés (mots et ponctuations)."""
    fin = len(texte) if fin is None else fin
    resultat = []
    for correspondance in MOTIF_JETON.finditer(texte, debut, fin):
        resultat.append(
            {
                "texte": correspondance.group(0),
                "debut": correspondance.start(),
                "fin": correspondance.end(),
            }
        )
    return resultat


def paragraphes(texte: str) -> list[dict[str, Any]]:
    """Découpe le texte en blocs affichables, avec leurs positions absolues."""
    blocs: list[dict[str, Any]] = []
    position = 0
    for morceau in texte.split("\n"):
        if morceau.strip():
            blocs.append(
                {
                    "debut": position,
                    "fin": position + len(morceau),
                    "texte": morceau,
                }
            )
        position += len(morceau) + 1
    if not blocs and texte:
        blocs.append({"debut": 0, "fin": len(texte), "texte": texte})
    return blocs


def chercher_occurrences(
    texte: str,
    chaine: str,
    sensible_casse: bool = False,
    mots_entiers: bool = True,
    contexte: int = 50,
) -> list[dict[str, Any]]:
    """Occurrences d'une chaîne dans le texte, avec contexte gauche/droit."""
    chaine = chaine.strip()
    if not chaine:
        return []
    motif = re.escape(chaine)
    if mots_entiers:
        motif = rf"(?<!\w){motif}(?!\w)"
    drapeaux = 0 if sensible_casse else re.IGNORECASE
    resultats = []
    for correspondance in re.finditer(motif, texte, drapeaux):
        debut, fin = correspondance.span()
        resultats.append(
            {
                "debut": debut,
                "fin": fin,
                "surface": texte[debut:fin],
                "gauche": texte[max(0, debut - contexte) : debut].replace("\n", " "),
                "droite": texte[fin : fin + contexte].replace("\n", " "),
            }
        )
    return resultats


def ajuster_bornes(texte: str, debut: int, fin: int) -> tuple[int, int]:
    """Supprime les blancs en tête et en fin de sélection."""
    debut = max(0, min(debut, len(texte)))
    fin = max(0, min(fin, len(texte)))
    while debut < fin and texte[debut].isspace():
        debut += 1
    while fin > debut and texte[fin - 1].isspace():
        fin -= 1
    return debut, fin


def annoter_occurrences(
    cx: sqlite3.Connection,
    document_id: int,
    occurrences: Iterable[dict[str, Any]],
    label: str,
    entity_id: str | None = None,
    statut: str | None = None,
    origine: str = "manuelle",
    completer_existantes: bool = True,
) -> dict[str, Any]:
    """Annote plusieurs occurrences d'un coup.

    Lorsqu'une mention existe déjà exactement aux mêmes positions — cas
    fréquent avec les entités détectées dans le XML-TEI — elle est complétée
    si elle n'est reliée à aucune entité et qu'une entité est fournie ici ;
    sinon elle est laissée intacte et comptée comme « déjà présente ».
    """
    creees, completees, ignorees, erreurs = 0, 0, 0, []
    for occurrence in occurrences:
        existante = cx.execute(
            "SELECT id, entity_id FROM annotations"
            " WHERE document_id = ? AND debut = ? AND fin = ?",
            (document_id, occurrence["debut"], occurrence["fin"]),
        ).fetchone()
        if existante is not None:
            if completer_existantes and entity_id and not existante["entity_id"]:
                try:
                    modifier_annotation(
                        cx,
                        existante["id"],
                        entity_id=entity_id,
                        label=label,
                        statut=statut or "a_verifier",
                    )
                    completees += 1
                except ErreurAnnotation as exc:
                    erreurs.append(str(exc))
            else:
                ignorees += 1
            continue
        try:
            creer_annotation(
                cx,
                document_id,
                occurrence["debut"],
                occurrence["fin"],
                label,
                entity_id=entity_id,
                statut=statut,
                origine=origine,
            )
            creees += 1
        except ErreurAnnotation as exc:
            if "existe déjà" in str(exc):
                ignorees += 1
            else:
                erreurs.append(str(exc))
    return {
        "creees": creees,
        "completees": completees,
        "ignorees": ignorees,
        "erreurs": erreurs,
    }
