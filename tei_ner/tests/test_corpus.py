"""Tests de l'import et de la consultation du corpus."""

from __future__ import annotations

import annotation as annotation_module
import corpus
from tests.conftest import NON_TEI, TEI_MAL_FORME, TEI_MINIMAL


def test_import_cree_le_document_et_conserve_la_source(cx):
    compte_rendu = corpus.importer_fichier(cx, TEI_MINIMAL, "essai.xml")
    assert compte_rendu["statut"] == "importe"
    document = corpus.lire_document(cx, compte_rendu["document_id"])
    assert document.titre == "Lettre d'essai"
    assert document.tei_id == "essai"
    assert document.xml_source == TEI_MINIMAL
    assert document.nb_caracteres == len(document.texte)


def test_import_reprend_les_entites_deja_encodees(cx):
    compte_rendu = corpus.importer_fichier(cx, TEI_MINIMAL, "essai.xml")
    annotations = annotation_module.annotations_dict(cx, compte_rendu["document_id"])
    assert len(annotations) == compte_rendu["annotations_detectees"] == 3
    assert all(a["origine"] == "tei" for a in annotations)
    assert all(a["statut"] == "non_resolue" for a in annotations)


def test_import_sans_reprise_des_annotations(cx):
    compte_rendu = corpus.importer_fichier(
        cx, TEI_MINIMAL, "essai.xml", reprendre_annotations_tei=False
    )
    assert compte_rendu["annotations_detectees"] == 0
    assert annotation_module.annotations_dict(cx, compte_rendu["document_id"]) == []


def test_doublon_detecte_par_empreinte(cx):
    corpus.importer_fichier(cx, TEI_MINIMAL, "essai.xml")
    second = corpus.importer_fichier(cx, TEI_MINIMAL, "copie.xml")
    assert second["statut"] == "doublon"
    assert len(corpus.lister_documents(cx)) == 1


def test_fichier_invalide_signale_sans_bloquer(cx):
    compte_rendu = corpus.importer_fichier(cx, TEI_MAL_FORME, "casse.xml")
    assert compte_rendu["statut"] == "invalide"
    assert "mal formé" in compte_rendu["message"]
    documents = corpus.lister_documents(cx)
    assert len(documents) == 1 and documents[0].statut == "invalide"


def test_fichier_non_tei_signale(cx):
    compte_rendu = corpus.importer_fichier(cx, NON_TEI, "autre.xml")
    assert compte_rendu["statut"] == "invalide"


def test_suppression_document_supprime_ses_annotations(cx, document):
    assert annotation_module.annotations_dict(cx, document.id)
    corpus.supprimer_document(cx, document.id)
    assert corpus.lire_document(cx, document.id) is None
    assert annotation_module.annotations_dict(cx) == []


def test_texte_balise_echappe_le_html(cx, document):
    annotations = annotation_module.annotations_dict(cx, document.id)
    rendu = corpus.texte_balise("<script>a</script> Delacroix", annotations[:0])
    assert "&lt;script&gt;" in rendu
    assert "<script>" not in rendu
