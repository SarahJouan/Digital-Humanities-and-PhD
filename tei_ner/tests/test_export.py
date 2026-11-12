"""Tests des exports JSON, TEI et JSONL."""

from __future__ import annotations

import io
import json
import zipfile

import annotation as annotation_module
import entity_manager
import export


def _corpus_annote(cx, document):
    personne = entity_manager.creer_entite(
        cx, "PERSON", "Eugène Delacroix", variants=["Delacroix"],
        description="Peintre français", validation_status="validee",
    )
    lieu = entity_manager.creer_entite(cx, "PLACE", "Paris", validation_status="brouillon")
    detectee = next(
        a for a in annotation_module.annotations_dict(cx, document.id)
        if a["surface"] == "Delacroix"
    )
    annotation_module.relier_entite(cx, [detectee["id"]], personne.entity_id)
    annotation_module.changer_statut(cx, [detectee["id"]], "validee")
    debut = document.texte.index("Paris")
    annotation_module.creer_annotation(
        cx, document.id, debut, debut + 5, "PLACE", lieu.entity_id, statut="a_verifier"
    )
    return personne, lieu


def test_referentiel_json_contient_les_champs_attendus(cx, document):
    personne, _ = _corpus_annote(cx, document)
    donnees = export.referentiel_json(cx, "toutes")
    fiche = next(f for f in donnees["entites"] if f["entity_id"] == personne.entity_id)
    for champ in (
        "entity_id", "entity_type", "canonical_name", "variants", "description",
        "metadata", "sources", "validation_status", "created_at", "updated_at",
    ):
        assert champ in fiche
    assert fiche["nb_occurrences"] == 1
    assert fiche["documents"] == [document.id]
    assert donnees["manifeste"]["convention_offsets"]["normalisation"] == "NFC"


def test_referentiel_separe_valide_et_non_valide(cx, document):
    _corpus_annote(cx, document)
    assert export.referentiel_json(cx, "validees")["nb_entites"] == 1
    assert export.referentiel_json(cx, "non_validees")["nb_entites"] == 1


def test_jsonl_offsets_coherents(cx, document):
    _corpus_annote(cx, document)
    for granularite in ("document", "paragraphe"):
        enregistrements = export.lignes_jsonl(cx, "toutes", granularite)
        assert enregistrements
        assert export.verifier_jsonl(enregistrements) == []
        for enregistrement in enregistrements:
            for entite in enregistrement["entities"]:
                extrait = enregistrement["text"][entite["start"]:entite["end"]]
                assert extrait == entite["text"]


def test_jsonl_traçabilite(cx, document):
    _corpus_annote(cx, document)
    enregistrements = export.lignes_jsonl(cx, "toutes", "document")
    enregistrement = enregistrements[0]
    assert enregistrement["meta"]["document_id"] == document.id
    assert enregistrement["meta"]["nom_fichier"] == "essai.xml"
    for entite in enregistrement["entities"]:
        assert entite["entity_id"]
        assert entite["annotation_id"]


def test_jsonl_filtre_sur_les_donnees_validees(cx, document):
    _corpus_annote(cx, document)
    validees = export.lignes_jsonl(cx, "validees", "document")
    non_validees = export.lignes_jsonl(cx, "non_validees", "document")
    assert sum(len(e["entities"]) for e in validees) == 1
    assert sum(len(e["entities"]) for e in non_validees) == 1


def test_jsonl_exclut_les_mentions_non_resolues_par_defaut(cx, document):
    enregistrements = export.lignes_jsonl(cx, "toutes", "document")
    assert sum(len(e["entities"]) for e in enregistrements) == 0
    avec = export.lignes_jsonl(cx, "toutes", "document", inclure_non_resolues=True)
    assert sum(len(e["entities"]) for e in avec) == 3


def test_jsonl_detecte_une_incoherence(cx, document):
    _corpus_annote(cx, document)
    enregistrements = export.lignes_jsonl(cx, "toutes", "document")
    enregistrements[0]["entities"][0]["end"] += 3
    assert export.verifier_jsonl(enregistrements)


def test_export_tei_valide_et_trace(cx, document):
    _corpus_annote(cx, document)
    resultats = export.documents_tei(cx, "toutes", "mixte")
    assert len(resultats) == 1
    resultat = resultats[0]
    assert resultat["xml_valide"]
    assert resultat["nb_annotations"] == 4  # 3 détectées dans le TEI + 1 ajoutée
    assert 'ref="#PERSON_0001"' in resultat["xml"]
    assert 'ref="#PLACE_0001"' in resultat["xml"]


def test_archive_complete(cx, document):
    _corpus_annote(cx, document)
    donnees = export.construire_archive(cx, portee="toutes")
    archive = zipfile.ZipFile(io.BytesIO(donnees))
    noms = archive.namelist()
    assert "manifeste.json" in noms
    assert "referentiel/entites-validees.json" in noms
    assert "referentiel/entites-non_validees.json" in noms
    assert "jsonl/corpus-validees.jsonl" in noms
    assert "tei/essai.xml" in noms
    assert "originaux/essai.xml" in noms
    # Le fichier d'origine est conservé à l'identique.
    assert archive.read("originaux/essai.xml").decode("utf-8") == document.xml_source
    manifeste = json.loads(archive.read("manifeste.json"))
    assert manifeste["convention_offsets"]["intervalle"] == "semi-ouvert [start, end["
