"""Gestion du référentiel d'entités nommées."""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Iterable

from database import transaction
from models import Entite, TYPES_ENTITES_DEFAUT, maintenant


class ErreurEntite(Exception):
    """Opération invalide sur le référentiel."""


# --------------------------------------------------------------------------
# Identifiants
# --------------------------------------------------------------------------
MOTIF_ID = re.compile(r"^[A-Z][A-Z0-9_]*_(\d{4,})$")


def prochain_identifiant(cx: sqlite3.Connection, entity_type: str) -> str:
    """Identifiant stable de la forme TYPE_0001, jamais réattribué."""
    prefixe = entity_type.upper()
    lignes = cx.execute(
        "SELECT entity_id FROM entites WHERE entity_id LIKE ?", (f"{prefixe}_%",)
    ).fetchall()
    maximum = 0
    for ligne in lignes:
        correspondance = MOTIF_ID.match(ligne["entity_id"])
        if correspondance and ligne["entity_id"].startswith(prefixe + "_"):
            maximum = max(maximum, int(correspondance.group(1)))
    # On tient aussi compte des identifiants déjà attribués puis supprimés.
    compteur_cle = f"compteur_{prefixe}"
    ligne = cx.execute("SELECT valeur FROM meta WHERE cle = ?", (compteur_cle,)).fetchone()
    if ligne:
        try:
            maximum = max(maximum, int(json.loads(ligne["valeur"])))
        except (ValueError, json.JSONDecodeError):
            pass
    suivant = maximum + 1
    cx.execute(
        "INSERT INTO meta(cle, valeur) VALUES(?, ?) "
        "ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
        (compteur_cle, json.dumps(suivant)),
    )
    return f"{prefixe}_{suivant:04d}"


def types_entites(cx: sqlite3.Connection) -> dict[str, str]:
    """Types disponibles : les six types initiaux plus ceux ajoutés par l'usager."""
    ligne = cx.execute("SELECT valeur FROM meta WHERE cle = 'types_entites'").fetchone()
    types = dict(TYPES_ENTITES_DEFAUT)
    if ligne:
        try:
            types.update(json.loads(ligne["valeur"]))
        except json.JSONDecodeError:
            pass
    return types


def ajouter_type(cx: sqlite3.Connection, code: str, libelle: str) -> dict[str, str]:
    code = re.sub(r"[^A-Z0-9_]", "", code.upper())
    if not code:
        raise ErreurEntite("Le code du type doit contenir des lettres majuscules.")
    types = types_entites(cx)
    personnalises = {c: l for c, l in types.items() if c not in TYPES_ENTITES_DEFAUT}
    personnalises[code] = libelle or code
    cx.execute(
        "INSERT INTO meta(cle, valeur) VALUES('types_entites', ?) "
        "ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
        (json.dumps(personnalises, ensure_ascii=False),),
    )
    cx.commit()
    return types_entites(cx)


# --------------------------------------------------------------------------
# Lecture
# --------------------------------------------------------------------------
def _entite_depuis_ligne(
    ligne: sqlite3.Row, variantes: list[str], sources: list[str]
) -> Entite:
    try:
        metadata = json.loads(ligne["metadata"] or "{}")
    except json.JSONDecodeError:
        metadata = {}
    return Entite(
        entity_id=ligne["entity_id"],
        entity_type=ligne["entity_type"],
        canonical_name=ligne["canonical_name"],
        description=ligne["description"] or "",
        variants=variantes,
        sources=sources,
        metadata=metadata,
        validation_status=ligne["validation_status"],
        note=ligne["note"] or "",
        created_at=ligne["created_at"],
        updated_at=ligne["updated_at"],
    )


def lire_entite(cx: sqlite3.Connection, entity_id: str) -> Entite | None:
    ligne = cx.execute(
        "SELECT * FROM entites WHERE entity_id = ?", (entity_id,)
    ).fetchone()
    if ligne is None:
        return None
    variantes = [
        r["variante"]
        for r in cx.execute(
            "SELECT variante FROM variantes WHERE entity_id = ? ORDER BY variante",
            (entity_id,),
        )
    ]
    sources = [
        r["source"]
        for r in cx.execute(
            "SELECT source FROM sources WHERE entity_id = ? ORDER BY id", (entity_id,)
        )
    ]
    return _entite_depuis_ligne(ligne, variantes, sources)


def lister_entites(
    cx: sqlite3.Connection,
    recherche: str = "",
    entity_type: str | None = None,
    statut: str | None = None,
    limite: int | None = None,
) -> list[Entite]:
    """Recherche par nom canonique, variante, identifiant, description ou type."""
    conditions: list[str] = []
    params: list[Any] = []
    if entity_type:
        conditions.append("e.entity_type = ?")
        params.append(entity_type)
    if statut:
        conditions.append("e.validation_status = ?")
        params.append(statut)
    if recherche:
        motif = f"%{recherche.strip()}%"
        conditions.append(
            "(e.entity_id LIKE ? OR e.canonical_name LIKE ? OR e.description LIKE ? "
            "OR EXISTS (SELECT 1 FROM variantes v WHERE v.entity_id = e.entity_id "
            "AND v.variante LIKE ?))"
        )
        params.extend([motif, motif, motif, motif])
    sql = "SELECT e.* FROM entites e"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY e.entity_type, e.canonical_name"
    if limite:
        sql += " LIMIT ?"
        params.append(limite)
    lignes = cx.execute(sql, tuple(params)).fetchall()
    identifiants = [l["entity_id"] for l in lignes]
    variantes = _grouper(cx, "variantes", "variante", identifiants)
    sources = _grouper(cx, "sources", "source", identifiants)
    return [
        _entite_depuis_ligne(
            l, variantes.get(l["entity_id"], []), sources.get(l["entity_id"], [])
        )
        for l in lignes
    ]


def _grouper(
    cx: sqlite3.Connection, table: str, colonne: str, identifiants: list[str]
) -> dict[str, list[str]]:
    if not identifiants:
        return {}
    resultat: dict[str, list[str]] = {}
    # Découpage pour rester sous la limite de variables liées de SQLite.
    for i in range(0, len(identifiants), 500):
        lot = identifiants[i : i + 500]
        marqueurs = ",".join("?" * len(lot))
        sql = (
            f"SELECT entity_id, {colonne} AS v FROM {table} "  # noqa: S608
            f"WHERE entity_id IN ({marqueurs}) ORDER BY id"
        )
        for ligne in cx.execute(sql, tuple(lot)):
            resultat.setdefault(ligne["entity_id"], []).append(ligne["v"])
    return resultat


def dictionnaire_entites(cx: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    return {e.entity_id: e.to_json_dict() for e in lister_entites(cx)}


# --------------------------------------------------------------------------
# Écriture
# --------------------------------------------------------------------------
def creer_entite(
    cx: sqlite3.Connection,
    entity_type: str,
    canonical_name: str,
    description: str = "",
    variants: Iterable[str] = (),
    sources: Iterable[str] = (),
    metadata: dict[str, Any] | None = None,
    validation_status: str = "brouillon",
    note: str = "",
    entity_id: str | None = None,
) -> Entite:
    canonical_name = (canonical_name or "").strip()
    if not canonical_name:
        raise ErreurEntite("Le nom canonique est obligatoire.")
    if entity_type not in types_entites(cx):
        raise ErreurEntite(f"Type d'entité inconnu : {entity_type}")
    with transaction(cx):
        if entity_id:
            existe = cx.execute(
                "SELECT 1 FROM entites WHERE entity_id = ?", (entity_id,)
            ).fetchone()
            if existe:
                raise ErreurEntite(f"L'identifiant {entity_id} est déjà utilisé.")
        else:
            entity_id = prochain_identifiant(cx, entity_type)
        horodatage = maintenant()
        cx.execute(
            "INSERT INTO entites(entity_id, entity_type, canonical_name, description,"
            " metadata, validation_status, note, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (
                entity_id,
                entity_type,
                canonical_name,
                description or "",
                json.dumps(metadata or {}, ensure_ascii=False),
                validation_status,
                note or "",
                horodatage,
                horodatage,
            ),
        )
        _remplacer_liens(cx, entity_id, variants, sources, canonical_name)
    return lire_entite(cx, entity_id)  # type: ignore[return-value]


def modifier_entite(
    cx: sqlite3.Connection,
    entity_id: str,
    **champs: Any,
) -> Entite:
    entite = lire_entite(cx, entity_id)
    if entite is None:
        raise ErreurEntite(f"Entité introuvable : {entity_id}")
    canonical_name = champs.get("canonical_name", entite.canonical_name).strip()
    if not canonical_name:
        raise ErreurEntite("Le nom canonique est obligatoire.")
    entity_type = champs.get("entity_type", entite.entity_type)
    if entity_type not in types_entites(cx):
        raise ErreurEntite(f"Type d'entité inconnu : {entity_type}")
    with transaction(cx):
        cx.execute(
            "UPDATE entites SET entity_type = ?, canonical_name = ?, description = ?,"
            " metadata = ?, validation_status = ?, note = ?, updated_at = ?"
            " WHERE entity_id = ?",
            (
                entity_type,
                canonical_name,
                champs.get("description", entite.description) or "",
                json.dumps(
                    champs.get("metadata", entite.metadata) or {}, ensure_ascii=False
                ),
                champs.get("validation_status", entite.validation_status),
                champs.get("note", entite.note) or "",
                maintenant(),
                entity_id,
            ),
        )
        _remplacer_liens(
            cx,
            entity_id,
            champs.get("variants", entite.variants),
            champs.get("sources", entite.sources),
            canonical_name,
        )
    return lire_entite(cx, entity_id)  # type: ignore[return-value]


def _remplacer_liens(
    cx: sqlite3.Connection,
    entity_id: str,
    variants: Iterable[str],
    sources: Iterable[str],
    canonical_name: str,
) -> None:
    cx.execute("DELETE FROM variantes WHERE entity_id = ?", (entity_id,))
    cx.execute("DELETE FROM sources WHERE entity_id = ?", (entity_id,))
    vues: set[str] = set()
    for variante in list(variants) + [canonical_name]:
        variante = (variante or "").strip()
        if not variante or variante in vues:
            continue
        vues.add(variante)
        cx.execute(
            "INSERT OR IGNORE INTO variantes(entity_id, variante) VALUES(?, ?)",
            (entity_id, variante),
        )
    vues_sources: set[str] = set()
    for source in sources:
        source = (source or "").strip()
        if not source or source in vues_sources:
            continue
        vues_sources.add(source)
        cx.execute(
            "INSERT OR IGNORE INTO sources(entity_id, source) VALUES(?, ?)",
            (entity_id, source),
        )


def supprimer_entite(cx: sqlite3.Connection, entity_id: str) -> int:
    """Supprime une fiche. Les annotations liées sont déliées (entity_id = NULL)."""
    nb = cx.execute(
        "SELECT COUNT(*) AS n FROM annotations WHERE entity_id = ?", (entity_id,)
    ).fetchone()["n"]
    with transaction(cx):
        cx.execute(
            "UPDATE annotations SET entity_id = NULL, statut = 'non_resolue',"
            " modifie_le = ? WHERE entity_id = ?",
            (maintenant(), entity_id),
        )
        cx.execute("DELETE FROM entites WHERE entity_id = ?", (entity_id,))
    return int(nb)


def ajouter_variante(cx: sqlite3.Connection, entity_id: str, variante: str) -> None:
    variante = (variante or "").strip()
    if not variante:
        return
    with transaction(cx):
        cx.execute(
            "INSERT OR IGNORE INTO variantes(entity_id, variante) VALUES(?, ?)",
            (entity_id, variante),
        )
        cx.execute(
            "UPDATE entites SET updated_at = ? WHERE entity_id = ?",
            (maintenant(), entity_id),
        )


def fusionner(cx: sqlite3.Connection, source_id: str, cible_id: str) -> dict[str, Any]:
    """Fusionne deux fiches APRÈS confirmation explicite de l'usager.

    Aucune fusion n'est jamais déclenchée automatiquement.
    """
    source = lire_entite(cx, source_id)
    cible = lire_entite(cx, cible_id)
    if source is None or cible is None:
        raise ErreurEntite("Entité source ou cible introuvable.")
    if source_id == cible_id:
        raise ErreurEntite("Les deux entités sont identiques.")
    nb = cx.execute(
        "SELECT COUNT(*) AS n FROM annotations WHERE entity_id = ?", (source_id,)
    ).fetchone()["n"]
    variantes = list(dict.fromkeys(cible.variants + source.variants + [source.canonical_name]))
    sources_doc = list(dict.fromkeys(cible.sources + source.sources))
    with transaction(cx):
        cx.execute(
            "UPDATE annotations SET entity_id = ?, modifie_le = ? WHERE entity_id = ?",
            (cible_id, maintenant(), source_id),
        )
        cx.execute("DELETE FROM entites WHERE entity_id = ?", (source_id,))
        _remplacer_liens(cx, cible_id, variantes, sources_doc, cible.canonical_name)
        cx.execute(
            "UPDATE entites SET updated_at = ? WHERE entity_id = ?",
            (maintenant(), cible_id),
        )
    return {"annotations_transferees": int(nb), "variantes": len(variantes)}


# --------------------------------------------------------------------------
# Recherche de correspondances et doublons
# --------------------------------------------------------------------------
def clef_comparaison(texte: str) -> str:
    """Forme normalisée pour comparer deux dénominations."""
    texte = unicodedata.normalize("NFKD", texte or "")
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    texte = texte.lower()
    texte = re.sub(r"\b(m|mr|mme|mlle|dr|st|ste|monsieur|madame|le|la|les|de|du|des|d)\b", " ", texte)
    texte = re.sub(r"[^a-z0-9]+", " ", texte)
    return " ".join(texte.split())


def chercher_correspondances(
    cx: sqlite3.Connection, mention: str, entity_type: str | None = None, limite: int = 10
) -> list[tuple[Entite, float]]:
    """Entités candidates pour une mention, triées par score décroissant."""
    clef = clef_comparaison(mention)
    if not clef:
        return []
    resultats: list[tuple[Entite, float]] = []
    for entite in lister_entites(cx, entity_type=entity_type):
        meilleur = 0.0
        for forme in [entite.canonical_name, *entite.variants]:
            clef_forme = clef_comparaison(forme)
            if not clef_forme:
                continue
            if clef_forme == clef:
                meilleur = 1.0
                break
            score = SequenceMatcher(None, clef, clef_forme).ratio()
            if clef in clef_forme or clef_forme in clef:
                score = max(score, 0.85)
            meilleur = max(meilleur, score)
        if meilleur >= 0.6:
            resultats.append((entite, round(meilleur, 3)))
    resultats.sort(key=lambda t: (-t[1], t[0].canonical_name))
    return resultats[:limite]


def detecter_doublons(
    cx: sqlite3.Connection, seuil: float = 0.86
) -> list[dict[str, Any]]:
    """Couples d'entités potentiellement redondantes (sans fusion automatique)."""
    entites = lister_entites(cx)
    par_type: dict[str, list[Entite]] = {}
    for entite in entites:
        par_type.setdefault(entite.entity_type, []).append(entite)

    doublons: list[dict[str, Any]] = []
    for entity_type, groupe in par_type.items():
        formes = [
            (e, {clef_comparaison(f) for f in [e.canonical_name, *e.variants] if f})
            for e in groupe
        ]
        for i in range(len(formes)):
            entite_a, clefs_a = formes[i]
            for j in range(i + 1, len(formes)):
                entite_b, clefs_b = formes[j]
                if clefs_a & clefs_b:
                    doublons.append(
                        {
                            "type": entity_type,
                            "a": entite_a,
                            "b": entite_b,
                            "score": 1.0,
                            "motif": "dénomination identique après normalisation",
                        }
                    )
                    continue
                meilleur = 0.0
                for ca in clefs_a:
                    for cb in clefs_b:
                        meilleur = max(meilleur, SequenceMatcher(None, ca, cb).ratio())
                if meilleur >= seuil:
                    doublons.append(
                        {
                            "type": entity_type,
                            "a": entite_a,
                            "b": entite_b,
                            "score": round(meilleur, 3),
                            "motif": "dénominations très proches",
                        }
                    )
    doublons.sort(key=lambda d: -d["score"])
    return doublons
