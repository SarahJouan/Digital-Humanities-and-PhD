"""Tests du référentiel d'entités."""

from __future__ import annotations

import pytest

import entity_manager


def test_identifiants_stables_et_non_reattribues(cx):
    premiere = entity_manager.creer_entite(cx, "PERSON", "Eugène Delacroix")
    seconde = entity_manager.creer_entite(cx, "PERSON", "Jean-Baptiste Pierret")
    assert premiere.entity_id == "PERSON_0001"
    assert seconde.entity_id == "PERSON_0002"
    entity_manager.supprimer_entite(cx, seconde.entity_id)
    troisieme = entity_manager.creer_entite(cx, "PERSON", "Charles de Mornay")
    assert troisieme.entity_id == "PERSON_0003"


def test_identifiants_separes_par_type(cx):
    personne = entity_manager.creer_entite(cx, "PERSON", "Ingres")
    lieu = entity_manager.creer_entite(cx, "PLACE", "Rome")
    assert personne.entity_id.startswith("PERSON_")
    assert lieu.entity_id.startswith("PLACE_")


def test_nom_canonique_obligatoire(cx):
    with pytest.raises(entity_manager.ErreurEntite):
        entity_manager.creer_entite(cx, "PERSON", "   ")


def test_identifiant_deja_utilise_refuse(cx):
    entity_manager.creer_entite(cx, "PERSON", "Gros", entity_id="PERSON_0042")
    with pytest.raises(entity_manager.ErreurEntite):
        entity_manager.creer_entite(cx, "PERSON", "Autre", entity_id="PERSON_0042")


def test_le_nom_canonique_figure_parmi_les_variantes(cx):
    entite = entity_manager.creer_entite(
        cx, "PERSON", "Eugène Delacroix", variants=["Delacroix"]
    )
    assert "Eugène Delacroix" in entite.variants
    assert "Delacroix" in entite.variants


def test_recherche_par_nom_variante_identifiant_et_type(cx):
    entity_manager.creer_entite(
        cx, "PERSON", "Eugène Delacroix", variants=["M. Delacroix"],
        description="Peintre français",
    )
    entity_manager.creer_entite(cx, "PLACE", "Tanger")
    assert len(entity_manager.lister_entites(cx, recherche="Delacroix")) == 1
    assert len(entity_manager.lister_entites(cx, recherche="M. Dela")) == 1
    assert len(entity_manager.lister_entites(cx, recherche="PERSON_0001")) == 1
    assert len(entity_manager.lister_entites(cx, recherche="Peintre")) == 1
    assert len(entity_manager.lister_entites(cx, entity_type="PLACE")) == 1


def test_doublons_detectes_sans_fusion(cx):
    entity_manager.creer_entite(cx, "PERSON", "Eugène Delacroix")
    entity_manager.creer_entite(cx, "PERSON", "Eugene Delacroix")
    doublons = entity_manager.detecter_doublons(cx)
    assert len(doublons) == 1
    # Les deux fiches existent toujours : rien n'est fusionné automatiquement.
    assert len(entity_manager.lister_entites(cx)) == 2


def test_doublons_ignorent_les_types_differents(cx):
    entity_manager.creer_entite(cx, "PERSON", "Nice")
    entity_manager.creer_entite(cx, "PLACE", "Nice")
    assert entity_manager.detecter_doublons(cx) == []


def test_correspondances_pour_une_mention(cx):
    entity_manager.creer_entite(
        cx, "PERSON", "Eugène Delacroix", variants=["M. Delacroix"]
    )
    resultats = entity_manager.chercher_correspondances(cx, "Delacroix", "PERSON")
    assert resultats and resultats[0][0].entity_id == "PERSON_0001"


def test_fusion_reporte_les_mentions(cx, document):
    import annotation as annotation_module

    source = entity_manager.creer_entite(cx, "PLACE", "Paris", variants=["Lutèce"])
    cible = entity_manager.creer_entite(cx, "PLACE", "Paris (France)")
    texte = document.texte
    debut = texte.index("Paris")
    creee = annotation_module.creer_annotation(
        cx, document.id, debut, debut + 5, "PLACE", source.entity_id
    )
    rapport = entity_manager.fusionner(cx, source.entity_id, cible.entity_id)
    assert rapport["annotations_transferees"] == 1
    assert entity_manager.lire_entite(cx, source.entity_id) is None
    fusionnee = entity_manager.lire_entite(cx, cible.entity_id)
    assert "Lutèce" in fusionnee.variants
    assert annotation_module.lire_annotation(cx, creee.id).entity_id == cible.entity_id


def test_suppression_delie_les_mentions(cx, document):
    import annotation as annotation_module

    entite = entity_manager.creer_entite(cx, "PLACE", "Paris")
    debut = document.texte.index("Paris")
    creee = annotation_module.creer_annotation(
        cx, document.id, debut, debut + 5, "PLACE", entite.entity_id
    )
    entity_manager.supprimer_entite(cx, entite.entity_id)
    restante = annotation_module.lire_annotation(cx, creee.id)
    assert restante is not None
    assert restante.entity_id is None
    assert restante.statut == "non_resolue"


def test_ajout_d_un_type_personnalise(cx):
    types = entity_manager.ajouter_type(cx, "artwork", "Œuvre d'art")
    assert types["ARTWORK"] == "Œuvre d'art"
    entite = entity_manager.creer_entite(cx, "ARTWORK", "Sardanapale")
    assert entite.entity_id == "ARTWORK_0001"
