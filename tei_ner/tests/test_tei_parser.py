"""Tests de l'analyse et de la réécriture XML-TEI."""

from __future__ import annotations

import pytest

import tei_parser
from tests.conftest import NON_TEI, TEI_MAL_FORME, TEI_MINIMAL


def test_analyse_extrait_le_texte_et_les_metadonnees():
    analyse = tei_parser.analyser(TEI_MINIMAL, "essai.xml")
    assert "M. Delacroix se rendit à Paris le 3 mai." in analyse.texte
    assert analyse.tei_id == "essai"
    assert analyse.metadonnees["titre"] == "Lettre d'essai"
    assert analyse.metadonnees["langue"] == "français"
    # Le teiHeader n'appartient pas au texte éditorial.
    assert "Anonyme" not in analyse.texte


def test_les_espaces_sont_reduits_et_les_blocs_separes():
    analyse = tei_parser.analyser(TEI_MINIMAL, "essai.xml")
    assert "\n" in analyse.texte
    assert "  " not in analyse.texte
    assert "l'École des beaux-arts" in analyse.texte


def test_detection_des_entites_deja_encodees():
    analyse = tei_parser.analyser(TEI_MINIMAL, "essai.xml")
    trouvees = {(a["label"], a["surface"]) for a in analyse.annotations_existantes}
    assert ("PERSON", "Delacroix") in trouvees
    assert ("PLACE", "Rome") in trouvees
    assert ("ORG", "l'Institut") in trouvees
    for item in analyse.annotations_existantes:
        assert analyse.texte[item["debut"]:item["fin"]] == item["surface"]


def test_fichier_mal_forme_refuse():
    with pytest.raises(tei_parser.ErreurTEI):
        tei_parser.analyser(TEI_MAL_FORME, "casse.xml")


def test_fichier_non_tei_refuse():
    with pytest.raises(tei_parser.ErreurTEI):
        tei_parser.analyser(NON_TEI, "autre.xml")


def test_export_inline_place_la_balise_au_bon_endroit():
    analyse = tei_parser.analyser(TEI_MINIMAL, "essai.xml")
    debut = analyse.texte.index("Paris")
    resultat = tei_parser.exporter_tei(
        analyse,
        [
            {
                "debut": debut,
                "fin": debut + 5,
                "label": "PLACE",
                "entity_id": "PLACE_0001",
                "surface": "Paris",
                "statut": "validee",
            }
        ],
        {
            "PLACE_0001": {
                "entity_id": "PLACE_0001",
                "entity_type": "PLACE",
                "canonical_name": "Paris",
                "variants": ["Lutèce"],
                "description": "",
                "sources": [],
                "validation_status": "validee",
            }
        },
    )
    assert resultat.inserees == 1
    assert not resultat.reportees
    assert '<placeName ref="#PLACE_0001">Paris</placeName>' in resultat.xml
    assert tei_parser.valider_xml(resultat.xml)[0]
    # Le référentiel est déclaré dans standOff, les renvois sont résolubles.
    assert '<place xml:id="PLACE_0001"' in resultat.xml
    # Les choix d'encodage sont documentés.
    assert "annotation-tei-ner" in resultat.xml


def test_export_ne_modifie_pas_la_source():
    analyse = tei_parser.analyser(TEI_MINIMAL, "essai.xml")
    debut = analyse.texte.index("Paris")
    tei_parser.exporter_tei(
        analyse,
        [{"debut": debut, "fin": debut + 5, "label": "PLACE",
          "entity_id": "PLACE_0001", "surface": "Paris", "statut": "validee"}],
        {},
    )
    seconde = tei_parser.analyser(analyse.xml_source, "essai.xml")
    assert seconde.texte == analyse.texte
    assert "PLACE_0001" not in analyse.xml_source


def test_balise_existante_enrichie_au_lieu_d_etre_imbriquee():
    analyse = tei_parser.analyser(TEI_MINIMAL, "essai.xml")
    cible = next(
        a for a in analyse.annotations_existantes if a["surface"] == "Delacroix"
    )
    resultat = tei_parser.exporter_tei(
        analyse,
        [{"debut": cible["debut"], "fin": cible["fin"], "label": "PERSON",
          "entity_id": "PERSON_0001", "surface": "Delacroix", "statut": "validee"}],
        {},
    )
    assert '<persName ref="#PERSON_0001">Delacroix</persName>' in resultat.xml
    assert "<persName ref=\"#PERSON_0001\"><persName" not in resultat.xml


def test_ref_editorial_preexistant_non_ecrase():
    analyse = tei_parser.analyser(TEI_MINIMAL, "essai.xml")
    cible = next(a for a in analyse.annotations_existantes if a["surface"] == "Rome")
    resultat = tei_parser.exporter_tei(
        analyse,
        [{"debut": cible["debut"], "fin": cible["fin"], "label": "PLACE",
          "entity_id": "PLACE_0009", "surface": "Rome", "statut": "validee"}],
        {},
    )
    assert 'ref="#rome"' in resultat.xml
    assert len(resultat.reportees) == 1
    # L'annotation est conservée dans standOff plutôt que perdue.
    assert "listAnnotation" in resultat.xml


def test_mode_standoff_laisse_le_texte_intact():
    analyse = tei_parser.analyser(TEI_MINIMAL, "essai.xml")
    debut = analyse.texte.index("Paris")
    resultat = tei_parser.exporter_tei(
        analyse,
        [{"debut": debut, "fin": debut + 5, "label": "PLACE",
          "entity_id": "PLACE_0001", "surface": "Paris", "statut": "validee"}],
        {},
        mode="standoff",
    )
    assert resultat.inserees == 0
    assert '<placeName ref="#PLACE_0001">' not in resultat.xml
    assert "#char=" in resultat.xml
    assert tei_parser.valider_xml(resultat.xml)[0]


def test_chevauchement_reporte_en_standoff():
    """Deux mentions qui se recouvrent : la seconde part en standOff."""
    analyse = tei_parser.analyser(TEI_MINIMAL, "essai.xml")
    debut_long = analyse.texte.index("se rendit")
    debut_paris = analyse.texte.index("Paris")
    annotations = [
        {"debut": debut_long, "fin": debut_paris + 5, "label": "OTHER",
         "entity_id": None, "surface": analyse.texte[debut_long:debut_paris + 5],
         "statut": "a_verifier"},
        {"debut": debut_paris, "fin": debut_paris + 5, "label": "PLACE",
         "entity_id": "PLACE_0001", "surface": "Paris", "statut": "validee"},
    ]
    resultat = tei_parser.exporter_tei(analyse, annotations, {})
    assert len(resultat.reportees) == 1
    assert "chevauchement" in resultat.reportees[0]["motif"]
    assert resultat.reportees[0]["surface"] == "Paris"
    assert "#char=" in resultat.xml


def test_mention_traversant_plusieurs_elements_reportee():
    analyse = tei_parser.analyser(TEI_MINIMAL, "essai.xml")
    fin = analyse.texte.index("Delacroix") + len("Delacroix")
    annotations = [
        {"debut": 0, "fin": fin, "label": "PERSON", "entity_id": "PERSON_0001",
         "surface": analyse.texte[0:fin], "statut": "a_verifier"},
    ]
    resultat = tei_parser.exporter_tei(analyse, annotations, {})
    assert len(resultat.reportees) == 1
    assert "plusieurs éléments" in resultat.reportees[0]["motif"]
