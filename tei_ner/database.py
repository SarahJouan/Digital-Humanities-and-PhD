"""Accès à la base SQLite locale.

Toutes les requêtes sont paramétrées. Le module expose une couche mince
(ouverture, schéma, CRUD de bas niveau, sauvegarde / restauration) ;
la logique métier se trouve dans annotation.py, entity_manager.py, etc.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from models import maintenant

# Emplacement par défaut : <racine du projet>/data/corpus.db
RACINE = Path(__file__).resolve().parent
DOSSIER_DONNEES = RACINE / "data"
DOSSIER_SAUVEGARDES = RACINE / "backups"
DOSSIER_EXPORTS = RACINE / "exports"
CHEMIN_BASE_DEFAUT = DOSSIER_DONNEES / "corpus.db"

SCHEMA_VERSION = 2

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    cle   TEXT PRIMARY KEY,
    valeur TEXT
);

CREATE TABLE IF NOT EXISTS documents (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    nom_fichier    TEXT NOT NULL,
    titre          TEXT NOT NULL DEFAULT '',
    tei_id         TEXT,
    empreinte      TEXT NOT NULL,
    texte          TEXT NOT NULL DEFAULT '',
    metadonnees    TEXT NOT NULL DEFAULT '{}',
    xml_source     TEXT NOT NULL DEFAULT '',
    statut         TEXT NOT NULL DEFAULT 'importe',
    message_erreur TEXT,
    nb_caracteres  INTEGER NOT NULL DEFAULT 0,
    cree_le        TEXT NOT NULL,
    modifie_le     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entites (
    entity_id         TEXT PRIMARY KEY,
    entity_type       TEXT NOT NULL,
    canonical_name    TEXT NOT NULL,
    description       TEXT NOT NULL DEFAULT '',
    metadata          TEXT NOT NULL DEFAULT '{}',
    validation_status TEXT NOT NULL DEFAULT 'brouillon',
    note              TEXT NOT NULL DEFAULT '',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS variantes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL REFERENCES entites(entity_id) ON DELETE CASCADE,
    variante  TEXT NOT NULL,
    UNIQUE (entity_id, variante)
);

CREATE TABLE IF NOT EXISTS sources (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL REFERENCES entites(entity_id) ON DELETE CASCADE,
    source    TEXT NOT NULL,
    UNIQUE (entity_id, source)
);

CREATE TABLE IF NOT EXISTS annotations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    entity_id   TEXT REFERENCES entites(entity_id) ON DELETE SET NULL,
    label       TEXT NOT NULL,
    debut       INTEGER NOT NULL,
    fin         INTEGER NOT NULL,
    surface     TEXT NOT NULL DEFAULT '',
    statut      TEXT NOT NULL DEFAULT 'a_verifier',
    origine     TEXT NOT NULL DEFAULT 'manuelle',
    note        TEXT NOT NULL DEFAULT '',
    tei_xml_id  TEXT,
    cree_le     TEXT NOT NULL,
    modifie_le  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS imports (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    type       TEXT NOT NULL,
    fichier    TEXT NOT NULL,
    resume     TEXT NOT NULL DEFAULT '{}',
    cree_le    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS journal (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    horodatage TEXT NOT NULL,
    action  TEXT NOT NULL,
    detail  TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_ann_doc    ON annotations(document_id);
CREATE INDEX IF NOT EXISTS idx_ann_ent    ON annotations(entity_id);
CREATE INDEX IF NOT EXISTS idx_ann_pos    ON annotations(document_id, debut, fin);
CREATE INDEX IF NOT EXISTS idx_var_ent    ON variantes(entity_id);
CREATE INDEX IF NOT EXISTS idx_ent_type   ON entites(entity_type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_doc_empreinte ON documents(empreinte);
"""


class ErreurBase(Exception):
    """Erreur applicative liée à la base de données."""


# --------------------------------------------------------------------------
# Connexion
# --------------------------------------------------------------------------
def chemin_base(chemin: str | Path | None = None) -> Path:
    return Path(chemin) if chemin else CHEMIN_BASE_DEFAUT


def connecter(chemin: str | Path | None = None) -> sqlite3.Connection:
    """Ouvre (et crée si besoin) la base SQLite."""
    cible = chemin_base(chemin)
    cible.parent.mkdir(parents=True, exist_ok=True)
    cx = sqlite3.connect(str(cible), check_same_thread=False)
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys = ON")
    cx.execute("PRAGMA journal_mode = WAL")
    return cx


def initialiser(cx: sqlite3.Connection) -> None:
    """Crée le schéma s'il n'existe pas et enregistre sa version."""
    cx.executescript(SCHEMA)
    cx.execute(
        "INSERT INTO meta(cle, valeur) VALUES(?, ?) "
        "ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
        ("schema_version", str(SCHEMA_VERSION)),
    )
    cx.execute(
        "INSERT OR IGNORE INTO meta(cle, valeur) VALUES(?, ?)",
        ("creee_le", maintenant()),
    )
    cx.commit()


def ouvrir(chemin: str | Path | None = None) -> sqlite3.Connection:
    """Raccourci : connecte et initialise."""
    cx = connecter(chemin)
    initialiser(cx)
    return cx


@contextmanager
def transaction(cx: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Transaction explicite : commit en sortie, rollback en cas d'erreur."""
    try:
        yield cx
        cx.commit()
    except Exception:
        cx.rollback()
        raise


# --------------------------------------------------------------------------
# Paramètres applicatifs (table meta)
# --------------------------------------------------------------------------
def lire_parametre(cx: sqlite3.Connection, cle: str, defaut: Any = None) -> Any:
    ligne = cx.execute("SELECT valeur FROM meta WHERE cle = ?", (cle,)).fetchone()
    if ligne is None:
        return defaut
    try:
        return json.loads(ligne["valeur"])
    except (json.JSONDecodeError, TypeError):
        return ligne["valeur"]


def ecrire_parametre(cx: sqlite3.Connection, cle: str, valeur: Any) -> None:
    cx.execute(
        "INSERT INTO meta(cle, valeur) VALUES(?, ?) "
        "ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
        (cle, json.dumps(valeur, ensure_ascii=False)),
    )
    cx.commit()


def journaliser(cx: sqlite3.Connection, action: str, detail: str = "") -> None:
    cx.execute(
        "INSERT INTO journal(horodatage, action, detail) VALUES(?, ?, ?)",
        (maintenant(), action, detail),
    )
    cx.commit()


def lire_journal(cx: sqlite3.Connection, limite: int = 100) -> list[sqlite3.Row]:
    return cx.execute(
        "SELECT * FROM journal ORDER BY id DESC LIMIT ?", (limite,)
    ).fetchall()


# --------------------------------------------------------------------------
# Statistiques globales
# --------------------------------------------------------------------------
def compter(cx: sqlite3.Connection, table: str, where: str = "", params: tuple = ()) -> int:
    tables_autorisees = {
        "documents",
        "entites",
        "annotations",
        "variantes",
        "sources",
        "imports",
    }
    if table not in tables_autorisees:
        raise ErreurBase(f"Table inconnue : {table}")
    sql = f"SELECT COUNT(*) AS n FROM {table}"  # noqa: S608 - table validée ci-dessus
    if where:
        sql += f" WHERE {where}"
    return int(cx.execute(sql, params).fetchone()["n"])


def statistiques(cx: sqlite3.Connection) -> dict[str, int]:
    """Chiffres affichés sur le tableau de bord."""
    return {
        "documents": compter(cx, "documents"),
        "documents_invalides": compter(cx, "documents", "statut = ?", ("invalide",)),
        "entites": compter(cx, "entites"),
        "entites_validees": compter(cx, "entites", "validation_status = ?", ("validee",)),
        "annotations": compter(cx, "annotations"),
        "annotations_validees": compter(cx, "annotations", "statut = ?", ("validee",)),
        "annotations_a_verifier": compter(cx, "annotations", "statut = ?", ("a_verifier",)),
        "annotations_ambigues": compter(cx, "annotations", "statut = ?", ("ambigue",)),
        "annotations_non_resolues": compter(
            cx, "annotations", "statut = ? OR entity_id IS NULL", ("non_resolue",)
        ),
        "variantes": compter(cx, "variantes"),
    }


# --------------------------------------------------------------------------
# Sauvegarde et restauration
# --------------------------------------------------------------------------
def sauvegarder(
    cx: sqlite3.Connection, dossier: str | Path | None = None, etiquette: str = ""
) -> Path:
    """Copie cohérente de la base via l'API de sauvegarde SQLite."""
    cible_dossier = Path(dossier) if dossier else DOSSIER_SAUVEGARDES
    cible_dossier.mkdir(parents=True, exist_ok=True)
    horodatage = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffixe = f"-{etiquette}" if etiquette else ""
    cible = cible_dossier / f"corpus-{horodatage}{suffixe}.db"
    destination = sqlite3.connect(str(cible))
    try:
        with destination:
            cx.backup(destination)
    finally:
        destination.close()
    journaliser(cx, "sauvegarde", str(cible))
    return cible


def lister_sauvegardes(dossier: str | Path | None = None) -> list[Path]:
    cible_dossier = Path(dossier) if dossier else DOSSIER_SAUVEGARDES
    if not cible_dossier.exists():
        return []
    return sorted(cible_dossier.glob("corpus-*.db"), reverse=True)


def restaurer(
    chemin_sauvegarde: str | Path, chemin_cible: str | Path | None = None
) -> Path:
    """Remplace la base courante par une sauvegarde.

    Une copie de sécurité de la base remplacée est créée avant l'opération.
    La connexion éventuellement ouverte doit être fermée par l'appelant
    AVANT d'appeler cette fonction.
    """
    source = Path(chemin_sauvegarde)
    if not source.exists():
        raise ErreurBase(f"Sauvegarde introuvable : {source}")
    # Vérification minimale : le fichier doit être une base SQLite lisible.
    test = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        test.execute("SELECT COUNT(*) FROM documents").fetchone()
    except sqlite3.DatabaseError as exc:  # pragma: no cover - dépend du fichier
        raise ErreurBase(f"Fichier de sauvegarde invalide : {exc}") from exc
    finally:
        test.close()

    cible = chemin_base(chemin_cible)
    cible.parent.mkdir(parents=True, exist_ok=True)
    if cible.exists():
        secours = cible.with_name(
            f"{cible.stem}-avant-restauration-"
            f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
        )
        shutil.copy2(cible, secours)
    # Les fichiers annexes du mode WAL doivent disparaître avec la base.
    for annexe in (
        cible.with_name(cible.name + "-wal"),
        cible.with_name(cible.name + "-shm"),
    ):
        if annexe.exists():
            annexe.unlink()
    shutil.copy2(source, cible)
    return cible


def reinitialiser(cx: sqlite3.Connection) -> None:
    """Vide toutes les tables de travail (le schéma est conservé)."""
    with transaction(cx):
        for table in ("annotations", "variantes", "sources", "entites", "documents", "imports"):
            cx.execute(f"DELETE FROM {table}")  # noqa: S608 - noms littéraux
    journaliser(cx, "reinitialisation", "toutes les données de travail effacées")
