"""Structures de données et constantes de l'application.

Ce module ne dépend ni de Streamlit, ni de la base de données : il définit
le vocabulaire commun (types d'entités, statuts, conventions d'offsets)
utilisé par tous les autres modules.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# --------------------------------------------------------------------------
# Convention d'offsets (voir docs/CONVENTIONS.md)
# --------------------------------------------------------------------------
# Toutes les positions de caractères manipulées par l'application sont des
# indices Python dans la chaîne de texte brut du document, c'est-à-dire des
# indices de POINTS DE CODE Unicode (et non des octets, ni des « graphemes »,
# ni des unités UTF-16).
#
# Le texte brut est normalisé en NFC avant indexation. Les intervalles sont
# semi-ouverts : [start, end[, donc end - start == nombre de caractères.
UNICODE_NORMALISATION = "NFC"


def normaliser(texte: str) -> str:
    """Normalise une chaîne selon la convention d'offsets de l'application."""
    return unicodedata.normalize(UNICODE_NORMALISATION, texte)


# --------------------------------------------------------------------------
# Types d'entités
# --------------------------------------------------------------------------
TYPES_ENTITES_DEFAUT: dict[str, str] = {
    "PERSON": "Personne",
    "PLACE": "Lieu",
    "ORG": "Organisation",
    "WORK": "Œuvre",
    "EVENT": "Événement",
    "OTHER": "Autre",
}

# Correspondance type d'entité -> balise TEI utilisée à l'export en ligne.
# Un tuple (nom de balise, attributs supplémentaires).
BALISES_TEI: dict[str, tuple[str, dict[str, str]]] = {
    "PERSON": ("persName", {}),
    "PLACE": ("placeName", {}),
    "ORG": ("orgName", {}),
    "WORK": ("title", {}),
    "EVENT": ("rs", {"type": "event"}),
    "OTHER": ("rs", {"type": "other"}),
}

# Correspondance inverse, pour la détection des entités déjà encodées.
# clé = (nom de balise locale, valeur de @type ou None)
DETECTION_TEI: dict[tuple[str, str | None], str] = {
    ("persName", None): "PERSON",
    ("person", None): "PERSON",
    ("placeName", None): "PLACE",
    ("place", None): "PLACE",
    ("geogName", None): "PLACE",
    ("orgName", None): "ORG",
    ("org", None): "ORG",
    ("title", None): "WORK",
    ("rs", "person"): "PERSON",
    ("rs", "place"): "PLACE",
    ("rs", "org"): "ORG",
    ("rs", "work"): "WORK",
    ("rs", "event"): "EVENT",
    ("rs", "other"): "OTHER",
    ("name", "person"): "PERSON",
    ("name", "place"): "PLACE",
    ("name", "org"): "ORG",
    ("name", "event"): "EVENT",
}

# --------------------------------------------------------------------------
# Statuts
# --------------------------------------------------------------------------
STATUTS_ANNOTATION: dict[str, str] = {
    "a_verifier": "À vérifier",
    "validee": "Validée",
    "ambigue": "Ambiguë",
    "non_resolue": "Non résolue",
}

STATUTS_ENTITE: dict[str, str] = {
    "brouillon": "Brouillon",
    "a_verifier": "À vérifier",
    "validee": "Validée",
    "rejetee": "Rejetée",
}

ORIGINES_ANNOTATION: dict[str, str] = {
    "manuelle": "Saisie manuelle",
    "tei": "Détectée dans le XML-TEI",
    "excel": "Importée depuis un tableur",
}

STATUTS_DOCUMENT: dict[str, str] = {
    "importe": "Importé",
    "invalide": "Invalide",
    "en_cours": "En cours d'annotation",
    "termine": "Terminé",
}

NIVEAUX_ALERTE: dict[str, str] = {
    "erreur": "Erreur",
    "avertissement": "Avertissement",
    "information": "Information",
}


def maintenant() -> str:
    """Horodatage ISO 8601 (secondes) utilisé pour toutes les dates stockées."""
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


# --------------------------------------------------------------------------
# Dataclasses
# --------------------------------------------------------------------------
@dataclass
class Document:
    """Un document XML-TEI importé dans le corpus."""

    id: int | None = None
    nom_fichier: str = ""
    titre: str = ""
    tei_id: str | None = None
    empreinte: str = ""
    texte: str = ""
    metadonnees: dict[str, Any] = field(default_factory=dict)
    xml_source: str = ""
    statut: str = "importe"
    message_erreur: str | None = None
    nb_caracteres: int = 0
    cree_le: str = ""
    modifie_le: str = ""


@dataclass
class Entite:
    """Fiche du référentiel d'entités nommées."""

    entity_id: str = ""
    entity_type: str = "PERSON"
    canonical_name: str = ""
    description: str = ""
    variants: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    validation_status: str = "brouillon"
    note: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        """Représentation JSON du référentiel (format documenté dans le README)."""
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "canonical_name": self.canonical_name,
            "variants": list(self.variants),
            "description": self.description,
            "metadata": dict(self.metadata),
            "sources": list(self.sources),
            "validation_status": self.validation_status,
            "note": self.note,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class Annotation:
    """Mention annotée dans un document, reliée (ou non) à une entité."""

    id: int | None = None
    document_id: int = 0
    entity_id: str | None = None
    label: str = "PERSON"
    start: int = 0
    end: int = 0
    surface: str = ""
    statut: str = "a_verifier"
    origine: str = "manuelle"
    note: str = ""
    tei_xml_id: str | None = None
    cree_le: str = ""
    modifie_le: str = ""

    @property
    def longueur(self) -> int:
        return self.end - self.start


@dataclass
class Alerte:
    """Résultat d'un contrôle qualité."""

    code: str
    niveau: str
    message: str
    document_id: int | None = None
    annotation_id: int | None = None
    entity_id: str | None = None
    correction: str | None = None  # description de la correction proposée
    donnees: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Métadonnées spécifiques par type d'entité (champs proposés dans la fiche)
# --------------------------------------------------------------------------
CHAMPS_METADONNEES: dict[str, list[tuple[str, str]]] = {
    "PERSON": [
        ("naissance", "Date de naissance"),
        ("deces", "Date de décès"),
        ("profession", "Profession / fonction"),
        ("sexe", "Genre"),
        ("identifiant_externe", "Identifiant externe (VIAF, IdRef, Wikidata…)"),
    ],
    "PLACE": [
        ("type_lieu", "Type de lieu (ville, région, pays…)"),
        ("pays", "Pays actuel"),
        ("latitude", "Latitude"),
        ("longitude", "Longitude"),
        ("identifiant_externe", "Identifiant externe (GeoNames, Wikidata…)"),
    ],
    "ORG": [
        ("type_org", "Type d'organisation"),
        ("date_creation", "Date de création"),
        ("date_dissolution", "Date de dissolution"),
        ("lieu", "Lieu principal"),
        ("identifiant_externe", "Identifiant externe (ISNI, Wikidata…)"),
    ],
    "WORK": [
        ("auteur", "Auteur"),
        ("date_creation", "Date de création"),
        ("genre", "Genre / support"),
        ("identifiant_externe", "Identifiant externe"),
    ],
    "EVENT": [
        ("date_debut", "Date de début"),
        ("date_fin", "Date de fin"),
        ("lieu", "Lieu"),
        ("identifiant_externe", "Identifiant externe"),
    ],
    "OTHER": [
        ("categorie", "Catégorie libre"),
        ("identifiant_externe", "Identifiant externe"),
    ],
}
