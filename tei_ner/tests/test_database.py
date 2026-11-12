"""Tests de la base de données, des sauvegardes et de la restauration."""

from __future__ import annotations

import sqlite3

import pytest

import corpus
import database
import entity_manager
from tests.conftest import TEI_MINIMAL


def test_schema_cree_et_version_enregistree(cx):
    tables = {
        ligne["name"]
        for ligne in cx.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"documents", "entites", "variantes", "sources", "annotations",
            "imports", "journal", "meta"} <= tables
    assert int(database.lire_parametre(cx, "schema_version")) == database.SCHEMA_VERSION


def test_cles_etrangeres_actives(cx):
    assert cx.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        cx.execute(
            "INSERT INTO annotations(document_id, label, debut, fin, surface,"
            " statut, origine, note, cree_le, modifie_le)"
            " VALUES(9999, 'PERSON', 0, 1, 'x', 'a_verifier', 'manuelle', '', '', '')"
        )


def test_requetes_parametrees_resistent_a_l_injection(cx):
    entity_manager.creer_entite(cx, "PERSON", "Delacroix")
    malveillant = "'; DROP TABLE entites; --"
    assert entity_manager.lister_entites(cx, recherche=malveillant) == []
    # La table est toujours là.
    assert len(entity_manager.lister_entites(cx)) == 1


def test_parametres_et_journal(cx):
    database.ecrire_parametre(cx, "essai", {"a": [1, 2]})
    assert database.lire_parametre(cx, "essai") == {"a": [1, 2]}
    database.journaliser(cx, "test", "détail")
    assert database.lire_journal(cx, 1)[0]["action"] == "test"


def test_statistiques(cx, document):
    stats = database.statistiques(cx)
    assert stats["documents"] == 1
    assert stats["annotations"] == 3
    assert stats["annotations_non_resolues"] == 3


def test_compter_refuse_une_table_inconnue(cx):
    with pytest.raises(database.ErreurBase):
        database.compter(cx, "sqlite_master")


def test_sauvegarde_et_restauration(cx, tmp_path, document):
    dossier = tmp_path / "sauvegardes"
    chemin = database.sauvegarder(cx, dossier, "essai")
    assert chemin.exists()
    assert database.lister_sauvegardes(dossier) == [chemin]

    # Modification après la sauvegarde.
    corpus.supprimer_document(cx, document.id)
    assert database.statistiques(cx)["documents"] == 0
    base = tmp_path / "test.db"
    cx.close()

    database.restaurer(chemin, base)
    restauree = database.ouvrir(base)
    try:
        assert database.statistiques(restauree)["documents"] == 1
        documents = corpus.lister_documents(restauree)
        assert documents[0].nom_fichier == "essai.xml"
    finally:
        restauree.close()


def test_restauration_refuse_un_fichier_invalide(tmp_path):
    faux = tmp_path / "faux.db"
    faux.write_text("ceci n'est pas une base de données")
    with pytest.raises(database.ErreurBase):
        database.restaurer(faux, tmp_path / "cible.db")


def test_restauration_conserve_une_copie_de_securite(cx, tmp_path, document):
    chemin = database.sauvegarder(cx, tmp_path / "sauvegardes")
    base = tmp_path / "test.db"
    cx.close()
    database.restaurer(chemin, base)
    copies = list(tmp_path.glob("test-avant-restauration-*.db"))
    assert len(copies) == 1


def test_reinitialisation_conserve_le_schema(cx, document):
    entity_manager.creer_entite(cx, "PERSON", "Delacroix")
    database.reinitialiser(cx)
    stats = database.statistiques(cx)
    assert stats["documents"] == 0 and stats["entites"] == 0 and stats["annotations"] == 0
    # On peut réimporter immédiatement.
    assert corpus.importer_fichier(cx, TEI_MINIMAL, "essai.xml")["statut"] == "importe"
