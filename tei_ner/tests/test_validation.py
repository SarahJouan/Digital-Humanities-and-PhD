"""Tests des contrôles qualité."""

from __future__ import annotations

import annotation as annotation_module
import entity_manager
import validation
from models import maintenant


def _codes(alertes):
    return {a.code for a in alertes}


def test_corpus_sain_sans_erreur(cx, document):
    entite = entity_manager.creer_entite(cx, "PERSON", "Eugène Delacroix")
    detectee = next(
        a for a in annotation_module.annotations_dict(cx, document.id)
        if a["surface"] == "Delacroix"
    )
    annotation_module.relier_entite(cx, [detectee["id"]], entite.entity_id)
    alertes = validation.executer_controles(
        cx, ["positions", "coherence_types", "entites_referencees", "chevauchements"]
    )
    assert validation.resume(alertes)["erreur"] == 0


def test_type_incoherent_detecte_et_corrige(cx, document):
    entite = entity_manager.creer_entite(cx, "PLACE", "Paris")
    debut = document.texte.index("Paris")
    creee = annotation_module.creer_annotation(
        cx, document.id, debut, debut + 5, "PLACE", entite.entity_id
    )
    cx.execute("UPDATE annotations SET label = 'PERSON' WHERE id = ?", (creee.id,))
    cx.commit()
    alertes = validation.executer_controles(cx, ["coherence_types"])
    assert "type_incoherent" in _codes(alertes)
    rapport = validation.appliquer_corrections(cx, alertes)
    assert rapport["types_alignes"] == 1
    assert annotation_module.lire_annotation(cx, creee.id).label == "PLACE"
    assert validation.executer_controles(cx, ["coherence_types"]) == []


def test_entite_absente_detectee_et_corrigee(cx, document):
    entite = entity_manager.creer_entite(cx, "PLACE", "Paris")
    debut = document.texte.index("Paris")
    creee = annotation_module.creer_annotation(
        cx, document.id, debut, debut + 5, "PLACE", entite.entity_id
    )
    # Suppression directe en base, en contournant la logique applicative.
    cx.execute("PRAGMA foreign_keys = OFF")
    cx.execute("DELETE FROM entites WHERE entity_id = ?", (entite.entity_id,))
    cx.commit()
    cx.execute("PRAGMA foreign_keys = ON")
    alertes = validation.executer_controles(cx, ["entites_referencees"])
    assert "entite_absente" in _codes(alertes)
    validation.appliquer_corrections(cx, alertes)
    annotation = annotation_module.lire_annotation(cx, creee.id)
    assert annotation.entity_id is None and annotation.statut == "non_resolue"


def test_surface_divergente_detectee_et_corrigee(cx, document):
    debut = document.texte.index("Paris")
    creee = annotation_module.creer_annotation(
        cx, document.id, debut, debut + 5, "PLACE"
    )
    cx.execute("UPDATE annotations SET surface = 'Rome' WHERE id = ?", (creee.id,))
    cx.commit()
    alertes = validation.executer_controles(cx, ["positions"])
    assert "surface_divergente" in _codes(alertes)
    validation.appliquer_corrections(cx, alertes)
    assert annotation_module.lire_annotation(cx, creee.id).surface == "Paris"


def test_position_invalide_detectee(cx, document):
    debut = document.texte.index("Paris")
    creee = annotation_module.creer_annotation(
        cx, document.id, debut, debut + 5, "PLACE"
    )
    cx.execute("UPDATE annotations SET fin = 999999 WHERE id = ?", (creee.id,))
    cx.commit()
    alertes = validation.executer_controles(cx, ["positions"])
    assert "position_invalide" in _codes(alertes)
    validation.appliquer_corrections(cx, alertes)
    assert annotation_module.lire_annotation(cx, creee.id) is None


def test_chevauchement_detecte_et_corrige(cx, document):
    debut = document.texte.index("Paris")
    longue = annotation_module.creer_annotation(
        cx, document.id, debut - 2, debut + 5, "OTHER"
    )
    courte = annotation_module.creer_annotation(
        cx, document.id, debut, debut + 5, "PLACE"
    )
    alertes = validation.executer_controles(cx, ["chevauchements"])
    assert "chevauchement" in _codes(alertes)
    validation.appliquer_corrections(cx, alertes)
    restantes = [a.id for a in annotation_module.lister_annotations(cx, document.id)]
    assert courte.id not in restantes and longue.id in restantes


def test_mention_ambigue_detectee(cx, document):
    premiere = entity_manager.creer_entite(cx, "PLACE", "Paris (France)")
    seconde = entity_manager.creer_entite(cx, "PLACE", "Paris (Texas)")
    debut = document.texte.index("Paris")
    annotation_module.creer_annotation(
        cx, document.id, debut, debut + 5, "PLACE", premiere.entity_id
    )
    cx.execute(
        "INSERT INTO annotations(document_id, entity_id, label, debut, fin, surface,"
        " statut, origine, note, cree_le, modifie_le)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (document.id, seconde.entity_id, "PLACE", 0, 2, "Paris", "a_verifier",
         "manuelle", "", maintenant(), maintenant()),
    )
    cx.commit()
    alertes = validation.executer_controles(cx, ["mentions_ambigues"])
    assert "mention_ambigue" in _codes(alertes)
    validation.appliquer_corrections(cx, alertes)
    statuts = {a.statut for a in annotation_module.lister_annotations(cx)
               if a.surface == "Paris"}
    assert statuts == {"ambigue"}


def test_mentions_non_resolues_signalees(cx, document):
    alertes = validation.executer_controles(cx, ["non_resolues"])
    assert len(alertes) == 3
    assert all(a.niveau == "information" for a in alertes)


def test_champs_obligatoires(cx):
    entity_manager.creer_entite(cx, "PERSON", "Sans description", validation_status="validee")
    cx.execute("UPDATE entites SET canonical_name = '' WHERE entity_id = 'PERSON_0001'")
    cx.commit()
    alertes = validation.executer_controles(cx, ["champs_obligatoires"])
    assert "fiche_incomplete" in _codes(alertes)


def test_toutes_les_corrections_sont_proposees_avant_application(cx, document):
    """Aucune correction n'est appliquée par le simple fait de lancer les contrôles."""
    debut = document.texte.index("Paris")
    creee = annotation_module.creer_annotation(cx, document.id, debut, debut + 5, "PLACE")
    cx.execute("UPDATE annotations SET surface = 'faux' WHERE id = ?", (creee.id,))
    cx.commit()
    validation.executer_controles(cx)
    assert annotation_module.lire_annotation(cx, creee.id).surface == "faux"
