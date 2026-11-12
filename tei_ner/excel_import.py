"""Reprise des données anciennes depuis un tableur (Excel ou CSV).

Beaucoup de corpus sont d'abord dépouillés dans un tableur. Ce module permet
de téléverser ce fichier, d'associer ses colonnes aux champs de l'application,
de SIMULER l'import (aucune écriture), puis de l'appliquer après relecture.

Deux cibles sont possibles :

* « referentiel »  : chaque ligne décrit une entité (fiche) ;
* « annotations »  : chaque ligne décrit une mention située dans un document
  déjà importé (par positions de caractères, ou par recherche de la chaîne).
"""

from __future__ import annotations

import io
import json
import re
import sqlite3
import unicodedata
from typing import Any, Iterable

import pandas as pd

import annotation as annotation_module
import corpus
import entity_manager
from database import journaliser, transaction
from models import STATUTS_ANNOTATION, STATUTS_ENTITE, maintenant

SEPARATEURS_VARIANTES = re.compile(r"\s*[;|/]\s*|\s*,\s(?=[A-ZÀ-ÖØ-Þ])|\s*\n\s*")


class ErreurTableur(Exception):
    """Fichier tableur illisible ou correspondance de colonnes incomplète."""


# --------------------------------------------------------------------------
# Champs cibles
# --------------------------------------------------------------------------
CHAMPS_REFERENTIEL: dict[str, dict[str, Any]] = {
    "canonical_name": {"libelle": "Nom canonique", "obligatoire": True,
                       "indices": ["nom", "canonique", "libelle", "label", "entite", "name", "forme"]},
    "entity_type": {"libelle": "Type d'entité", "obligatoire": False,
                    "indices": ["type", "categorie", "classe", "nature"]},
    "entity_id": {"libelle": "Identifiant", "obligatoire": False,
                  "indices": ["id", "identifiant", "code", "cle"]},
    "variants": {"libelle": "Variantes (séparées par ; ou |)", "obligatoire": False,
                 "indices": ["variante", "variant", "forme", "alias", "graphie", "orthographe"]},
    "description": {"libelle": "Description", "obligatoire": False,
                    "indices": ["description", "notice", "commentaire", "note", "definition"]},
    "sources": {"libelle": "Sources", "obligatoire": False,
                "indices": ["source", "reference", "bibliographie", "provenance"]},
    "validation_status": {"libelle": "Statut de validation", "obligatoire": False,
                          "indices": ["statut", "validation", "etat", "status"]},
}

CHAMPS_ANNOTATIONS: dict[str, dict[str, Any]] = {
    "document": {"libelle": "Document (nom de fichier, titre ou identifiant)",
                 "obligatoire": True,
                 "indices": ["document", "fichier", "source", "texte", "oeuvre", "doc"]},
    "surface": {"libelle": "Mention telle qu'elle apparaît", "obligatoire": True,
                "indices": ["mention", "forme", "surface", "occurrence", "chaine", "extrait"]},
    "label": {"libelle": "Type d'entité", "obligatoire": False,
              "indices": ["type", "categorie", "classe", "label"]},
    "entity_id": {"libelle": "Identifiant d'entité", "obligatoire": False,
                  "indices": ["identifiant", "id", "entity id", "code", "cle", "uri"]},
    "canonical_name": {"libelle": "Nom canonique de l'entité", "obligatoire": False,
                       "indices": ["entite", "nom", "canonique", "entity", "reference",
                                   "renvoi", "vedette"]},
    "debut": {"libelle": "Position de début", "obligatoire": False,
              "indices": ["debut", "start", "offset", "position"]},
    "fin": {"libelle": "Position de fin", "obligatoire": False,
            "indices": ["fin", "end"]},
    "statut": {"libelle": "Statut", "obligatoire": False,
               "indices": ["statut", "status", "etat", "validation"]},
    "note": {"libelle": "Note", "obligatoire": False,
             "indices": ["note", "commentaire", "remarque"]},
}

CIBLES = {
    "referentiel": ("Référentiel d'entités", CHAMPS_REFERENTIEL),
    "annotations": ("Annotations (mentions)", CHAMPS_ANNOTATIONS),
}

# Valeurs textuelles acceptées pour les statuts.
SYNONYMES_STATUT_ENTITE = {
    "valide": "validee", "validee": "validee", "validé": "validee", "validée": "validee",
    "ok": "validee", "oui": "validee", "confirme": "validee", "confirmée": "validee",
    "brouillon": "brouillon", "draft": "brouillon", "nouveau": "brouillon",
    "a verifier": "a_verifier", "à vérifier": "a_verifier", "a_verifier": "a_verifier",
    "douteux": "a_verifier", "incertain": "a_verifier",
    "rejete": "rejetee", "rejetée": "rejetee", "rejetee": "rejetee", "non": "rejetee",
}
SYNONYMES_STATUT_ANNOTATION = {
    "valide": "validee", "validee": "validee", "validé": "validee", "validée": "validee",
    "ok": "validee", "oui": "validee",
    "a verifier": "a_verifier", "à vérifier": "a_verifier", "a_verifier": "a_verifier",
    "ambigu": "ambigue", "ambigue": "ambigue", "ambiguë": "ambigue", "douteux": "ambigue",
    "non resolu": "non_resolue", "non résolu": "non_resolue", "non_resolue": "non_resolue",
    "inconnu": "non_resolue",
}

SYNONYMES_TYPE = {
    "personne": "PERSON", "person": "PERSON", "per": "PERSON", "pers": "PERSON",
    "individu": "PERSON", "auteur": "PERSON", "persname": "PERSON",
    "lieu": "PLACE", "place": "PLACE", "loc": "PLACE", "localite": "PLACE",
    "ville": "PLACE", "geo": "PLACE", "placename": "PLACE",
    "organisation": "ORG", "organization": "ORG", "org": "ORG",
    "institution": "ORG", "societe": "ORG", "orgname": "ORG",
    "oeuvre": "WORK", "œuvre": "WORK", "work": "WORK", "titre": "WORK",
    "ouvrage": "WORK", "livre": "WORK", "tableau": "WORK",
    "evenement": "EVENT", "événement": "EVENT", "event": "EVENT",
    "autre": "OTHER", "other": "OTHER", "divers": "OTHER", "misc": "OTHER",
}


# --------------------------------------------------------------------------
# Lecture du fichier
# --------------------------------------------------------------------------
def lire_tableur(contenu: bytes, nom_fichier: str) -> dict[str, pd.DataFrame]:
    """Renvoie un DataFrame par feuille (une seule entrée pour un CSV)."""
    nom = (nom_fichier or "").lower()
    try:
        if nom.endswith((".csv", ".tsv", ".txt")):
            separateur = "\t" if nom.endswith(".tsv") else None
            texte = contenu.decode("utf-8-sig", errors="replace")
            cadre = pd.read_csv(
                io.StringIO(texte), sep=separateur, engine="python", dtype=str
            )
            return {"Feuille 1": cadre.fillna("")}
        feuilles = pd.read_excel(io.BytesIO(contenu), sheet_name=None, dtype=str)
    except Exception as exc:  # pandas lève des exceptions très variées
        raise ErreurTableur(
            f"Lecture impossible : {exc}. Formats acceptés : .xlsx, .xlsm, .csv, .tsv."
        ) from exc
    if not feuilles:
        raise ErreurTableur("Le fichier ne contient aucune feuille exploitable.")
    return {nom_feuille: cadre.fillna("") for nom_feuille, cadre in feuilles.items()}


def _normaliser_entete(entete: str) -> str:
    texte = unicodedata.normalize("NFKD", str(entete))
    texte = "".join(c for c in texte if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", texte).strip()


def deviner_correspondances(colonnes: Iterable[str], cible: str) -> dict[str, str]:
    """Associe automatiquement les colonnes du tableur aux champs de l'application."""
    champs = CIBLES[cible][1]
    colonnes = list(colonnes)
    normalisees = {colonne: _normaliser_entete(colonne) for colonne in colonnes}
    correspondances: dict[str, str] = {}
    prises: set[str] = set()
    for champ, definition in champs.items():
        meilleur, meilleur_score = None, 0.0
        for colonne in colonnes:
            if colonne in prises:
                continue
            entete = normalisees[colonne]
            if not entete:
                continue
            score = 0.0
            if entete == _normaliser_entete(champ):
                score = 1.0
            else:
                for indice in definition["indices"]:
                    if entete == indice:
                        score = max(score, 0.95)
                    elif entete.startswith(indice) or indice in entete.split():
                        score = max(score, 0.8)
                    elif indice in entete:
                        score = max(score, 0.6)
            if score > meilleur_score:
                meilleur, meilleur_score = colonne, score
        if meilleur and meilleur_score >= 0.6:
            correspondances[champ] = meilleur
            prises.add(meilleur)
    return correspondances


def _valeur(ligne: pd.Series, correspondances: dict[str, str], champ: str) -> str:
    colonne = correspondances.get(champ)
    if not colonne or colonne not in ligne.index:
        return ""
    valeur = ligne[colonne]
    if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
        return ""
    return str(valeur).strip()


def decouper_liste(valeur: str) -> list[str]:
    if not valeur:
        return []
    morceaux = [m.strip() for m in SEPARATEURS_VARIANTES.split(valeur) if m and m.strip()]
    if len(morceaux) <= 1 and "," in valeur:
        morceaux = [m.strip() for m in valeur.split(",") if m.strip()]
    return list(dict.fromkeys(morceaux))


def normaliser_type(valeur: str, types_connus: dict[str, str]) -> str | None:
    if not valeur:
        return None
    brut = valeur.strip()
    if brut.upper() in types_connus:
        return brut.upper()
    clef = _normaliser_entete(brut)
    if clef in SYNONYMES_TYPE:
        return SYNONYMES_TYPE[clef]
    for code, libelle in types_connus.items():
        if clef == _normaliser_entete(libelle):
            return code
    return None


def normaliser_statut(valeur: str, cible: str) -> str | None:
    if not valeur:
        return None
    clef = _normaliser_entete(valeur)
    table = SYNONYMES_STATUT_ENTITE if cible == "referentiel" else SYNONYMES_STATUT_ANNOTATION
    if clef in table:
        return table[clef]
    brut = valeur.strip()
    valides = STATUTS_ENTITE if cible == "referentiel" else STATUTS_ANNOTATION
    return brut if brut in valides else None


# --------------------------------------------------------------------------
# Simulation : référentiel
# --------------------------------------------------------------------------
def preparer_referentiel(
    cx: sqlite3.Connection,
    cadre: pd.DataFrame,
    correspondances: dict[str, str],
    type_par_defaut: str = "OTHER",
    statut_par_defaut: str = "a_verifier",
    sur_conflit: str = "completer",
    colonnes_metadonnees: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Analyse chaque ligne SANS rien écrire.

    sur_conflit : 'completer' (ajoute variantes et champs vides),
    'ignorer' (laisse la fiche existante intacte) ou 'creer' (crée une
    nouvelle fiche et signale le doublon, sans fusion automatique).
    """
    if "canonical_name" not in correspondances:
        raise ErreurTableur(
            "La colonne du nom canonique doit être associée avant la simulation."
        )
    types_connus = entity_manager.types_entites(cx)
    colonnes_metadonnees = colonnes_metadonnees or []
    existantes = entity_manager.lister_entites(cx)
    index_clef: dict[tuple[str, str], str] = {}
    for entite in existantes:
        for forme in [entite.canonical_name, *entite.variants]:
            clef = entity_manager.clef_comparaison(forme)
            if clef:
                index_clef.setdefault((entite.entity_type, clef), entite.entity_id)

    lignes: list[dict[str, Any]] = []
    noms_vus: dict[tuple[str, str], int] = {}
    for numero, (_, ligne) in enumerate(cadre.iterrows(), start=2):
        nom = _valeur(ligne, correspondances, "canonical_name")
        resultat: dict[str, Any] = {
            "ligne": numero,
            "action": "creer",
            "messages": [],
            "donnees": {},
        }
        if not nom:
            resultat["action"] = "ignorer"
            resultat["messages"].append("Nom canonique absent : ligne ignorée.")
            lignes.append(resultat)
            continue

        type_brut = _valeur(ligne, correspondances, "entity_type")
        entity_type = normaliser_type(type_brut, types_connus)
        if entity_type is None:
            entity_type = type_par_defaut
            if type_brut:
                resultat["messages"].append(
                    f"Type « {type_brut} » non reconnu : {type_par_defaut} appliqué."
                )
            else:
                resultat["messages"].append(f"Type absent : {type_par_defaut} appliqué.")

        statut = normaliser_statut(
            _valeur(ligne, correspondances, "validation_status"), "referentiel"
        ) or statut_par_defaut

        variantes = decouper_liste(_valeur(ligne, correspondances, "variants"))
        sources = decouper_liste(_valeur(ligne, correspondances, "sources"))
        metadonnees = {}
        for colonne in colonnes_metadonnees:
            if colonne in ligne.index:
                valeur = str(ligne[colonne]).strip()
                if valeur:
                    metadonnees[str(colonne)] = valeur

        identifiant_fourni = _valeur(ligne, correspondances, "entity_id")
        resultat["donnees"] = {
            "entity_id": identifiant_fourni or None,
            "entity_type": entity_type,
            "canonical_name": nom,
            "description": _valeur(ligne, correspondances, "description"),
            "variants": variantes,
            "sources": sources,
            "metadata": metadonnees,
            "validation_status": statut,
        }

        clef = entity_manager.clef_comparaison(nom)
        doublon_fichier = noms_vus.get((entity_type, clef))
        if doublon_fichier:
            resultat["messages"].append(
                f"Dénomination déjà présente ligne {doublon_fichier} du tableur."
            )
        noms_vus.setdefault((entity_type, clef), numero)

        cible_existante = None
        if identifiant_fourni:
            fiche = entity_manager.lire_entite(cx, identifiant_fourni)
            if fiche is not None:
                cible_existante = fiche.entity_id
                resultat["messages"].append(
                    f"L'identifiant {identifiant_fourni} existe déjà dans le référentiel."
                )
        if cible_existante is None:
            cible_existante = index_clef.get((entity_type, clef))
            if cible_existante:
                resultat["messages"].append(
                    f"Correspond probablement à la fiche existante {cible_existante}."
                )

        if cible_existante:
            resultat["cible"] = cible_existante
            if sur_conflit == "ignorer":
                resultat["action"] = "ignorer"
            elif sur_conflit == "completer":
                resultat["action"] = "completer"
            else:
                resultat["action"] = "creer"
                resultat["donnees"]["entity_id"] = None
                resultat["messages"].append(
                    "Une nouvelle fiche sera créée : aucune fusion automatique."
                )
        lignes.append(resultat)
    return lignes


def appliquer_referentiel(
    cx: sqlite3.Connection, lignes: list[dict[str, Any]], fichier: str
) -> dict[str, Any]:
    compte = {"creees": 0, "completees": 0, "ignorees": 0, "erreurs": 0}
    details: list[str] = []
    for resultat in lignes:
        donnees = resultat.get("donnees") or {}
        try:
            if resultat["action"] == "creer":
                entite = entity_manager.creer_entite(
                    cx,
                    entity_type=donnees["entity_type"],
                    canonical_name=donnees["canonical_name"],
                    description=donnees.get("description", ""),
                    variants=donnees.get("variants", ()),
                    sources=donnees.get("sources", ()),
                    metadata=donnees.get("metadata"),
                    validation_status=donnees.get("validation_status", "a_verifier"),
                    entity_id=donnees.get("entity_id") or None,
                )
                resultat["entity_id"] = entite.entity_id
                compte["creees"] += 1
            elif resultat["action"] == "completer":
                cible = resultat["cible"]
                fiche = entity_manager.lire_entite(cx, cible)
                if fiche is None:
                    compte["erreurs"] += 1
                    continue
                variantes = list(
                    dict.fromkeys(
                        fiche.variants + donnees.get("variants", []) + [donnees["canonical_name"]]
                    )
                )
                sources = list(dict.fromkeys(fiche.sources + donnees.get("sources", [])))
                metadonnees = {**donnees.get("metadata", {}), **fiche.metadata}
                entity_manager.modifier_entite(
                    cx,
                    cible,
                    description=fiche.description or donnees.get("description", ""),
                    variants=variantes,
                    sources=sources,
                    metadata=metadonnees,
                )
                resultat["entity_id"] = cible
                compte["completees"] += 1
            else:
                compte["ignorees"] += 1
        except Exception as exc:  # erreurs métier remontées à l'usager
            compte["erreurs"] += 1
            details.append(f"Ligne {resultat['ligne']} : {exc}")
    _enregistrer_import(cx, "referentiel", fichier, compte, details)
    return {**compte, "details": details}


# --------------------------------------------------------------------------
# Simulation : annotations
# --------------------------------------------------------------------------
def _index_documents(cx: sqlite3.Connection) -> dict[str, int]:
    index: dict[str, int] = {}
    for document in corpus.lister_documents(cx):
        for clef in filter(None, [document.nom_fichier, document.titre, document.tei_id]):
            index.setdefault(_normaliser_entete(clef), document.id)  # type: ignore[arg-type]
            index.setdefault(_normaliser_entete(str(clef).rsplit(".", 1)[0]), document.id)  # type: ignore[arg-type]
        index.setdefault(str(document.id), document.id)  # type: ignore[arg-type]
    return index


def preparer_annotations(
    cx: sqlite3.Connection,
    cadre: pd.DataFrame,
    correspondances: dict[str, str],
    document_par_defaut: int | None = None,
    type_par_defaut: str = "OTHER",
    statut_par_defaut: str = "a_verifier",
    creer_entites_manquantes: bool = False,
    toutes_occurrences: bool = False,
) -> list[dict[str, Any]]:
    """Analyse chaque ligne SANS rien écrire.

    Si les positions de début et de fin sont fournies et concordent avec le
    texte, elles sont utilisées telles quelles. Sinon, la mention est
    recherchée dans le texte du document (première occurrence, ou toutes
    si `toutes_occurrences`).
    """
    if "surface" not in correspondances:
        raise ErreurTableur("La colonne de la mention doit être associée.")
    types_connus = entity_manager.types_entites(cx)
    index_documents = _index_documents(cx)
    textes: dict[int, str] = {}
    for document in corpus.lister_documents(cx):
        complet = corpus.lire_document(cx, document.id)  # type: ignore[arg-type]
        if complet:
            textes[complet.id] = complet.texte  # type: ignore[index]

    index_noms: dict[tuple[str, str], str] = {}
    for entite in entity_manager.lister_entites(cx):
        for forme in [entite.canonical_name, *entite.variants]:
            clef = entity_manager.clef_comparaison(forme)
            if clef:
                index_noms.setdefault((entite.entity_type, clef), entite.entity_id)

    lignes: list[dict[str, Any]] = []
    for numero, (_, ligne) in enumerate(cadre.iterrows(), start=2):
        resultat: dict[str, Any] = {
            "ligne": numero,
            "action": "creer",
            "messages": [],
            "donnees": {},
            "occurrences": [],
        }
        surface = _valeur(ligne, correspondances, "surface")
        if not surface:
            resultat["action"] = "ignorer"
            resultat["messages"].append("Mention absente : ligne ignorée.")
            lignes.append(resultat)
            continue

        reference_document = _valeur(ligne, correspondances, "document")
        document_id = index_documents.get(_normaliser_entete(reference_document))
        if document_id is None and reference_document:
            document_id = index_documents.get(
                _normaliser_entete(reference_document.rsplit(".", 1)[0])
            )
        if document_id is None:
            document_id = document_par_defaut
            if reference_document:
                resultat["messages"].append(
                    f"Document « {reference_document} » introuvable dans le corpus."
                )
        if document_id is None or document_id not in textes:
            resultat["action"] = "erreur"
            resultat["messages"].append(
                "Aucun document cible : importez d'abord le fichier TEI correspondant."
            )
            lignes.append(resultat)
            continue

        texte = textes[document_id]
        label = normaliser_type(_valeur(ligne, correspondances, "label"), types_connus)
        if label is None:
            label = type_par_defaut
        statut = normaliser_statut(
            _valeur(ligne, correspondances, "statut"), "annotations"
        ) or statut_par_defaut

        # Résolution de l'entité
        entity_id = _valeur(ligne, correspondances, "entity_id") or None
        valeur_identifiant = entity_id
        if entity_id and entity_manager.lire_entite(cx, entity_id) is None:
            resultat["messages"].append(
                f"Aucune fiche ne porte l'identifiant « {entity_id} » : "
                "la valeur est traitée comme une dénomination."
            )
            entity_id = None
        if not entity_id:
            nom = _valeur(ligne, correspondances, "canonical_name") or valeur_identifiant or ""
            if nom:
                entity_id = index_noms.get(
                    (label, entity_manager.clef_comparaison(nom))
                )
                if not entity_id:
                    if creer_entites_manquantes:
                        resultat["entite_a_creer"] = {
                            "entity_type": label,
                            "canonical_name": nom,
                            "variants": [surface],
                        }
                        resultat["messages"].append(
                            f"L'entité « {nom} » sera créée ({label})."
                        )
                    else:
                        resultat["messages"].append(
                            f"Entité « {nom} » introuvable : mention laissée non résolue."
                        )

        # Localisation de la mention
        debut_brut = _valeur(ligne, correspondances, "debut")
        fin_brut = _valeur(ligne, correspondances, "fin")
        occurrences: list[dict[str, Any]] = []
        if debut_brut and fin_brut:
            try:
                debut, fin = int(float(debut_brut)), int(float(fin_brut))
            except ValueError:
                debut = fin = -1
            if 0 <= debut < fin <= len(texte) and texte[debut:fin] == surface:
                occurrences = [{"debut": debut, "fin": fin, "surface": surface}]
            else:
                resultat["messages"].append(
                    "Positions fournies incohérentes avec le texte : "
                    "recherche de la mention à la place."
                )
        if not occurrences:
            trouvees = annotation_module.chercher_occurrences(
                texte, surface, sensible_casse=False, mots_entiers=True
            )
            if not trouvees:
                trouvees = annotation_module.chercher_occurrences(
                    texte, surface, sensible_casse=False, mots_entiers=False
                )
            if not trouvees:
                resultat["action"] = "erreur"
                resultat["messages"].append(
                    f"Mention « {surface} » absente du texte du document {document_id}."
                )
                lignes.append(resultat)
                continue
            occurrences = trouvees if toutes_occurrences else trouvees[:1]
            if len(trouvees) > 1 and not toutes_occurrences:
                resultat["messages"].append(
                    f"{len(trouvees)} occurrences trouvées ; seule la première est retenue."
                )

        resultat["donnees"] = {
            "document_id": document_id,
            "label": label,
            "entity_id": entity_id,
            "statut": statut if entity_id or resultat.get("entite_a_creer") else "non_resolue",
            "note": _valeur(ligne, correspondances, "note"),
        }
        resultat["occurrences"] = occurrences
        lignes.append(resultat)
    return lignes


def appliquer_annotations(
    cx: sqlite3.Connection, lignes: list[dict[str, Any]], fichier: str
) -> dict[str, Any]:
    compte = {
        "creees": 0,
        "completees": 0,
        "ignorees": 0,
        "doublons": 0,
        "erreurs": 0,
        "entites_creees": 0,
    }
    details: list[str] = []
    for resultat in lignes:
        if resultat["action"] not in ("creer",):
            compte["ignorees"] += 1
            continue
        donnees = resultat["donnees"]
        entity_id = donnees.get("entity_id")
        try:
            if not entity_id and resultat.get("entite_a_creer"):
                fiche = entity_manager.creer_entite(
                    cx,
                    entity_type=resultat["entite_a_creer"]["entity_type"],
                    canonical_name=resultat["entite_a_creer"]["canonical_name"],
                    variants=resultat["entite_a_creer"].get("variants", ()),
                    validation_status="a_verifier",
                    note="Créée lors d'un import de tableur.",
                )
                entity_id = fiche.entity_id
                compte["entites_creees"] += 1
            rapport = annotation_module.annoter_occurrences(
                cx,
                donnees["document_id"],
                resultat["occurrences"],
                donnees["label"],
                entity_id=entity_id,
                statut=donnees["statut"],
                origine="excel",
            )
            compte["creees"] += rapport["creees"]
            compte["completees"] += rapport.get("completees", 0)
            compte["doublons"] += rapport["ignorees"]
            for erreur in rapport["erreurs"]:
                details.append(f"Ligne {resultat['ligne']} : {erreur}")
                compte["erreurs"] += 1
        except Exception as exc:
            compte["erreurs"] += 1
            details.append(f"Ligne {resultat['ligne']} : {exc}")
    _enregistrer_import(cx, "annotations", fichier, compte, details)
    return {**compte, "details": details}


def _enregistrer_import(
    cx: sqlite3.Connection,
    type_import: str,
    fichier: str,
    compte: dict[str, Any],
    details: list[str],
) -> None:
    with transaction(cx):
        cx.execute(
            "INSERT INTO imports(type, fichier, resume, cree_le) VALUES(?,?,?,?)",
            (
                type_import,
                fichier,
                json.dumps({"compte": compte, "details": details[:50]}, ensure_ascii=False),
                maintenant(),
            ),
        )
    journaliser(cx, f"import_tableur_{type_import}", f"{fichier} : {compte}")


def historique_imports(cx: sqlite3.Connection, limite: int = 50) -> list[dict[str, Any]]:
    lignes = cx.execute(
        "SELECT * FROM imports ORDER BY id DESC LIMIT ?", (limite,)
    ).fetchall()
    resultats = []
    for ligne in lignes:
        try:
            resume = json.loads(ligne["resume"])
        except json.JSONDecodeError:
            resume = {}
        resultats.append(
            {
                "id": ligne["id"],
                "type": ligne["type"],
                "fichier": ligne["fichier"],
                "date": ligne["cree_le"],
                "resume": resume.get("compte", {}),
            }
        )
    return resultats
