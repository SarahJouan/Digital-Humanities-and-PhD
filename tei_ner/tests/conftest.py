"""Fixtures communes aux tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

import corpus  # noqa: E402
import database  # noqa: E402

TEI_MINIMAL = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:id="essai">
  <teiHeader>
    <fileDesc>
      <titleStmt><title>Lettre d'essai</title><author>Anonyme</author></titleStmt>
      <publicationStmt><publisher>Tests</publisher><date when="2026">2026</date></publicationStmt>
      <sourceDesc><bibl>Corpus de test</bibl></sourceDesc>
    </fileDesc>
    <profileDesc><langUsage><language ident="fr">français</language></langUsage></profileDesc>
  </teiHeader>
  <text>
    <body>
      <div>
        <p>M. <persName>Delacroix</persName> se rendit à Paris le 3 mai.</p>
        <p>À <placeName ref="#rome">Rome</placeName>, il retrouva l'École
        des beaux-arts et <orgName>l'Institut</orgName>.</p>
      </div>
    </body>
  </text>
</TEI>
"""

TEI_MAL_FORME = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader><fileDesc><titleStmt><title>Cassé</title></titleStmt></fileDesc></teiHeader>
  <text><body><p>Balise non fermée.</body></text>
</TEI>
"""

NON_TEI = """<?xml version="1.0" encoding="UTF-8"?><racine><p>Bonjour</p></racine>"""


@pytest.fixture()
def cx(tmp_path):
    """Base SQLite neuve, isolée pour chaque test."""
    connexion = database.ouvrir(tmp_path / "test.db")
    yield connexion
    connexion.close()


@pytest.fixture()
def document(cx):
    """Un document de test importé dans le corpus."""
    compte_rendu = corpus.importer_fichier(cx, TEI_MINIMAL, "essai.xml")
    assert compte_rendu["statut"] == "importe"
    return corpus.lire_document(cx, compte_rendu["document_id"])
