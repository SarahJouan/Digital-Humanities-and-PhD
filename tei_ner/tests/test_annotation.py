"""Tests de la logique d'annotation."""

from __future__ import annotations

import pytest

import annotation as annotation_module
import entity_manager


def test_creation_calcule_la_surface(cx, document):
    debut = document.texte.index("Paris")
    creee = annotation_module.creer_annotation(
        cx, document.id, debut, debut + 5, "PLACE"
    )
    assert creee.surface == "Paris"
    assert creee.statut == "non_resolue"  # aucune entité associée
    assert creee.longueur == 5


def test_positions_hors_texte_refusees(cx, document):
    with pytest.raises(annotation_module.ErreurAnnotation):
        annotation_module.creer_annotation(cx, document.id, 0, 10**6, "PLACE")
    with pytest.raises(annotation_module.ErreurAnnotation):
        annotation_module.creer_annotation(cx, document.id, 10, 5, "PLACE")


def test_entite_inconnue_refusee(cx, document):
    with pytest.raises(annotation_module.ErreurAnnotation):
        annotation_module.creer_annotation(
            cx, document.id, 0, 2, "PERSON", entity_id="PERSON_9999"
        )


def test_doublon_exact_refuse(cx, document):
    debut = document.texte.index("Paris")
    annotation_module.creer_annotation(cx, document.id, debut, debut + 5, "PLACE")
    with pytest.raises(annotation_module.ErreurAnnotation):
        annotation_module.creer_annotation(cx, document.id, debut, debut + 5, "PLACE")


def test_recherche_occurrences_respecte_les_mots_entiers(cx, document):
    texte = "Rome, Romero et Rome."
    entiers = annotation_module.chercher_occurrences(texte, "Rome", mots_entiers=True)
    partiels = annotation_module.chercher_occurrences(texte, "Rome", mots_entiers=False)
    assert len(entiers) == 2
    assert len(partiels) == 3
    for occurrence in entiers:
        assert texte[occurrence["debut"]:occurrence["fin"]] == "Rome"


def test_annotation_en_lot_des_occurrences(cx, document):
    entite = entity_manager.creer_entite(cx, "PLACE", "Paris")
    occurrences = annotation_module.chercher_occurrences(document.texte, "Paris")
    rapport = annotation_module.annoter_occurrences(
        cx, document.id, occurrences, "PLACE", entite.entity_id
    )
    assert rapport["creees"] == len(occurrences)
    # Relancer n'ajoute rien.
    second = annotation_module.annoter_occurrences(
        cx, document.id, occurrences, "PLACE", entite.entity_id
    )
    assert second["creees"] == 0 and second["ignorees"] == len(occurrences)


def test_mention_existante_non_resolue_completee(cx, document):
    """Une mention détectée dans le TEI reçoit l'entité sans être dupliquée."""
    detectee = next(
        a for a in annotation_module.annotations_dict(cx, document.id)
        if a["surface"] == "Delacroix"
    )
    entite = entity_manager.creer_entite(cx, "PERSON", "Eugène Delacroix")
    rapport = annotation_module.annoter_occurrences(
        cx,
        document.id,
        [{"debut": detectee["debut"], "fin": detectee["fin"]}],
        "PERSON",
        entite.entity_id,
    )
    assert rapport["completees"] == 1 and rapport["creees"] == 0
    mise_a_jour = annotation_module.lire_annotation(cx, detectee["id"])
    assert mise_a_jour.entity_id == entite.entity_id
    assert mise_a_jour.statut == "a_verifier"


def test_jetons_et_bornes(cx, document):
    jetons = annotation_module.jetons(document.texte)
    assert jetons[0]["texte"] == "M"
    for jeton in jetons:
        assert document.texte[jeton["debut"]:jeton["fin"]] == jeton["texte"]
    debut, fin = annotation_module.ajuster_bornes(document.texte, 0, 4)
    assert document.texte[debut:fin].strip() == document.texte[debut:fin]


def test_paragraphes_positionnes(cx, document):
    blocs = annotation_module.paragraphes(document.texte)
    assert len(blocs) >= 2
    for bloc in blocs:
        assert document.texte[bloc["debut"]:bloc["fin"]] == bloc["texte"]


def test_changement_de_statut_et_rattachement_en_lot(cx, document):
    entite = entity_manager.creer_entite(cx, "PERSON", "Eugène Delacroix")
    identifiants = [a["id"] for a in annotation_module.annotations_dict(cx, document.id)]
    annotation_module.relier_entite(cx, identifiants[:1], entite.entity_id)
    annotation_module.changer_statut(cx, identifiants[:1], "validee")
    annotation = annotation_module.lire_annotation(cx, identifiants[0])
    assert annotation.entity_id == entite.entity_id
    assert annotation.label == "PERSON"
    assert annotation.statut == "validee"


def test_occurrences_d_une_entite_avec_contexte(cx, document):
    entite = entity_manager.creer_entite(cx, "PLACE", "Paris")
    debut = document.texte.index("Paris")
    annotation_module.creer_annotation(
        cx, document.id, debut, debut + 5, "PLACE", entite.entity_id
    )
    occurrences = annotation_module.occurrences_entite(cx, entite.entity_id)
    assert len(occurrences) == 1
    assert "[Paris]" in occurrences[0]["contexte"]
    assert occurrences[0]["document"] == "Lettre d'essai"


def test_suppression_d_annotation(cx, document):
    identifiants = [a["id"] for a in annotation_module.annotations_dict(cx, document.id)]
    annotation_module.supprimer_annotation(cx, identifiants[0])
    assert annotation_module.lire_annotation(cx, identifiants[0]) is None
    assert annotation_module.supprimer_annotations(cx, identifiants[1:]) == len(identifiants) - 1
    assert annotation_module.annotations_dict(cx, document.id) == []
