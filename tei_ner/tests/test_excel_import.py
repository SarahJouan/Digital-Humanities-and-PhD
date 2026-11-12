"""Tests de la reprise des données depuis un tableur."""

from __future__ import annotations

import io

import pandas as pd
import pytest

import annotation as annotation_module
import entity_manager
import excel_import


def test_lecture_xlsx_multi_feuilles():
    tampon = io.BytesIO()
    with pd.ExcelWriter(tampon) as writer:
        pd.DataFrame({"Nom": ["Paris"]}).to_excel(writer, sheet_name="Entités", index=False)
        pd.DataFrame({"Mention": ["Paris"]}).to_excel(writer, sheet_name="Mentions", index=False)
    feuilles = excel_import.lire_tableur(tampon.getvalue(), "ancien.xlsx")
    assert set(feuilles) == {"Entités", "Mentions"}


def test_lecture_csv():
    contenu = "Nom;Type\nParis;lieu\n".encode("utf-8")
    feuilles = excel_import.lire_tableur(contenu, "ancien.csv")
    cadre = feuilles["Feuille 1"]
    assert list(cadre.columns) == ["Nom", "Type"]


def test_fichier_illisible_refuse():
    with pytest.raises(excel_import.ErreurTableur):
        excel_import.lire_tableur(b"\x00\x01\x02 pas un tableur", "x.xlsx")


def test_correspondances_devinees():
    colonnes = ["Identifiant", "Nom retenu", "Catégorie", "Formes attestées", "Notice", "État"]
    correspondances = excel_import.deviner_correspondances(colonnes, "referentiel")
    assert correspondances["canonical_name"] == "Nom retenu"
    assert correspondances["entity_type"] == "Catégorie"
    assert correspondances["variants"] == "Formes attestées"
    assert correspondances["validation_status"] == "État"


def test_types_et_statuts_reconnus_en_francais():
    types = {"PERSON": "Personne", "PLACE": "Lieu", "ORG": "Organisation",
             "WORK": "Œuvre", "EVENT": "Événement", "OTHER": "Autre"}
    assert excel_import.normaliser_type("personne", types) == "PERSON"
    assert excel_import.normaliser_type("Lieu", types) == "PLACE"
    assert excel_import.normaliser_type("institution", types) == "ORG"
    assert excel_import.normaliser_type("œuvre", types) == "WORK"
    assert excel_import.normaliser_type("fantaisie", types) is None
    assert excel_import.normaliser_statut("validé", "referentiel") == "validee"
    assert excel_import.normaliser_statut("à vérifier", "annotations") == "a_verifier"


def test_decoupage_des_variantes():
    assert excel_import.decouper_liste("Delacroix; M. Delacroix | Eug. Delacroix") == [
        "Delacroix", "M. Delacroix", "Eug. Delacroix"
    ]
    assert excel_import.decouper_liste("") == []


def test_simulation_n_ecrit_rien(cx):
    cadre = pd.DataFrame({"Nom": ["Paris"], "Type": ["lieu"]})
    correspondances = excel_import.deviner_correspondances(cadre.columns, "referentiel")
    lignes = excel_import.preparer_referentiel(cx, cadre, correspondances)
    assert lignes[0]["action"] == "creer"
    assert entity_manager.lister_entites(cx) == []


def test_import_referentiel(cx):
    cadre = pd.DataFrame(
        {
            "Nom": ["Eugène Delacroix", "Paris", ""],
            "Type": ["personne", "lieu", "lieu"],
            "Variantes": ["Delacroix; M. Delacroix", "", ""],
            "Statut": ["validé", "à vérifier", ""],
            "Dates": ["1798-1863", "", ""],
        }
    )
    correspondances = excel_import.deviner_correspondances(cadre.columns, "referentiel")
    lignes = excel_import.preparer_referentiel(
        cx, cadre, correspondances, colonnes_metadonnees=["Dates"]
    )
    rapport = excel_import.appliquer_referentiel(cx, lignes, "ancien.xlsx")
    assert rapport["creees"] == 2 and rapport["ignorees"] == 1
    entite = entity_manager.lire_entite(cx, "PERSON_0001")
    assert entite.canonical_name == "Eugène Delacroix"
    assert "M. Delacroix" in entite.variants
    assert entite.validation_status == "validee"
    assert entite.metadata["Dates"] == "1798-1863"


def test_fiche_existante_completee_sans_fusion(cx):
    entity_manager.creer_entite(cx, "PERSON", "Eugène Delacroix")
    cadre = pd.DataFrame(
        {"Nom": ["Eugene Delacroix"], "Type": ["personne"], "Variantes": ["Eug. D."]}
    )
    correspondances = excel_import.deviner_correspondances(cadre.columns, "referentiel")
    lignes = excel_import.preparer_referentiel(
        cx, cadre, correspondances, sur_conflit="completer"
    )
    assert lignes[0]["action"] == "completer"
    excel_import.appliquer_referentiel(cx, lignes, "ancien.xlsx")
    assert len(entity_manager.lister_entites(cx)) == 1
    assert "Eug. D." in entity_manager.lire_entite(cx, "PERSON_0001").variants


def test_conflit_ignorer_et_creer(cx):
    entity_manager.creer_entite(cx, "PLACE", "Paris")
    cadre = pd.DataFrame({"Nom": ["Paris"], "Type": ["lieu"]})
    correspondances = excel_import.deviner_correspondances(cadre.columns, "referentiel")
    lignes = excel_import.preparer_referentiel(
        cx, cadre, correspondances, sur_conflit="ignorer"
    )
    excel_import.appliquer_referentiel(cx, lignes, "a.xlsx")
    assert len(entity_manager.lister_entites(cx)) == 1
    lignes = excel_import.preparer_referentiel(
        cx, cadre, correspondances, sur_conflit="creer"
    )
    excel_import.appliquer_referentiel(cx, lignes, "a.xlsx")
    assert len(entity_manager.lister_entites(cx)) == 2


def test_import_annotations_par_recherche(cx, document):
    entity_manager.creer_entite(cx, "PLACE", "Paris")
    cadre = pd.DataFrame(
        {
            "Fichier": ["essai.xml"],
            "Mention": ["Paris"],
            "Type": ["lieu"],
            "Entité": ["Paris"],
            "Statut": ["validé"],
        }
    )
    correspondances = excel_import.deviner_correspondances(cadre.columns, "annotations")
    lignes = excel_import.preparer_annotations(cx, cadre, correspondances)
    assert lignes[0]["action"] == "creer"
    assert lignes[0]["donnees"]["entity_id"] == "PLACE_0001"
    rapport = excel_import.appliquer_annotations(cx, lignes, "ancien.xlsx")
    assert rapport["creees"] == 1
    creee = [a for a in annotation_module.annotations_dict(cx, document.id)
             if a["surface"] == "Paris"][0]
    assert creee["entity_id"] == "PLACE_0001"
    assert creee["origine"] == "excel"
    assert creee["statut"] == "validee"


def test_import_annotations_avec_positions(cx, document):
    debut = document.texte.index("Paris")
    cadre = pd.DataFrame(
        {
            "Fichier": ["essai.xml"],
            "Mention": ["Paris"],
            "Type": ["lieu"],
            "Début": [debut],
            "Fin": [debut + 5],
        }
    )
    correspondances = excel_import.deviner_correspondances(cadre.columns, "annotations")
    assert correspondances["debut"] == "Début" and correspondances["fin"] == "Fin"
    lignes = excel_import.preparer_annotations(cx, cadre, correspondances)
    assert lignes[0]["occurrences"] == [{"debut": debut, "fin": debut + 5, "surface": "Paris"}]


def test_positions_incoherentes_basculent_sur_la_recherche(cx, document):
    cadre = pd.DataFrame(
        {"Fichier": ["essai.xml"], "Mention": ["Paris"], "Début": [0], "Fin": [5]}
    )
    correspondances = excel_import.deviner_correspondances(cadre.columns, "annotations")
    lignes = excel_import.preparer_annotations(cx, cadre, correspondances)
    assert "incohérentes" in " ".join(lignes[0]["messages"])
    assert lignes[0]["occurrences"][0]["surface"] == "Paris"


def test_mention_absente_signalee_sans_blocage(cx, document):
    cadre = pd.DataFrame(
        {
            "Fichier": ["essai.xml", "essai.xml"],
            "Mention": ["Berlin", "Paris"],
            "Type": ["lieu", "lieu"],
        }
    )
    correspondances = excel_import.deviner_correspondances(cadre.columns, "annotations")
    lignes = excel_import.preparer_annotations(cx, cadre, correspondances)
    assert lignes[0]["action"] == "erreur"
    assert lignes[1]["action"] == "creer"
    rapport = excel_import.appliquer_annotations(cx, lignes, "ancien.xlsx")
    assert rapport["creees"] == 1 and rapport["ignorees"] == 1


def test_creation_des_entites_manquantes(cx, document):
    cadre = pd.DataFrame(
        {"Fichier": ["essai.xml"], "Mention": ["Paris"], "Type": ["lieu"],
         "Entité": ["Paris"]}
    )
    correspondances = excel_import.deviner_correspondances(cadre.columns, "annotations")
    lignes = excel_import.preparer_annotations(
        cx, cadre, correspondances, creer_entites_manquantes=True
    )
    rapport = excel_import.appliquer_annotations(cx, lignes, "ancien.xlsx")
    assert rapport["entites_creees"] == 1
    assert entity_manager.lire_entite(cx, "PLACE_0001").canonical_name == "Paris"


def test_historique_des_imports(cx):
    cadre = pd.DataFrame({"Nom": ["Paris"], "Type": ["lieu"]})
    correspondances = excel_import.deviner_correspondances(cadre.columns, "referentiel")
    lignes = excel_import.preparer_referentiel(cx, cadre, correspondances)
    excel_import.appliquer_referentiel(cx, lignes, "ancien.xlsx")
    historique = excel_import.historique_imports(cx)
    assert historique[0]["fichier"] == "ancien.xlsx"
    assert historique[0]["resume"]["creees"] == 1
